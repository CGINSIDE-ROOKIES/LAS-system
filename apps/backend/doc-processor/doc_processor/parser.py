from pydantic import BaseModel, Field, ValidationError

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from typing import Literal
import re

from doc_processor.las_types import IRChunk, DocumentState, IRGroupState
from doc_processor.llms import midm as llm
from doc_processor.prompts import get_prompts
from doc_processor.core.ir import ir_grouper

prompts = get_prompts()

###################################################################################################
# STRUCTURED OUTPUT FORMS
###################################################################################################

"""
Reasoning과 관련해서, 이 필드를 CoT간접 유도를 위해서 저걸 먼저 생성하도록 유도가 필요
프롬팅에서 하던지 아니면 시스템적으로 할 수 있는건지?
"""

class TextPrelimCategorization(BaseModel):
    """"""
    reasoning: str = Field(
        description="이렇게 분류한 간단한 이유 한줄. 여기를 먼저 채워넣으세요!"
    )
    category: Literal["조문", "uncategorized"] = Field(
        description="이 텍스트의 분류, 하나만 고르세요."
    )


class TextCategorization(BaseModel):
    """"""
    reasoning: str = Field(
        description="이렇게 분류한 간단한 이유 한줄. 여기를 먼저 채워넣으세요!"
    )
    category: Literal["제목", "전문", "조문", "입력란", "기타"] = Field(
        description="이 텍스트의 분류, 하나만 고르세요."
    )

###################################################################################################

prelim_categorizer_llm = llm.with_structured_output(TextPrelimCategorization, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError), stop_after_attempt=3)
categorizer_llm = llm.with_structured_output(TextCategorization, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError), stop_after_attempt=3)

BYPASS_PRELIM = False

def document_splitter(state: DocumentState):
    ps = state.preprocess_state
    if ps == "uncategorized" and BYPASS_PRELIM:
        ps = "prelim"
    
    if ps == "uncategorized":
        return [Send("prelim_categorization_workers", IRGroupState(group_idx=i, ir_group=ir_group))
                for i, ir_group in enumerate(state.ir_groups)]
    elif ps == "prelim":
        return [Send("categorization_workers", IRGroupState(group_idx=i, ir_group=ir_group))
                for i, ir_group in enumerate(state.ir_groups)]
    elif ps == "finished":
        return END
    else:
        raise TypeError("unexpected preprocess state!!!")


def document_reducer(state: DocumentState):
    # ir_groups_temp needs to be cleared!!! (or it'll accumulate)
    sorted_ir_groups = sorted(state.ir_groups_temp, key=lambda x: x[0])
    next_state = "prelim" if state.preprocess_state == "uncategorized" else "finished"
    groups = [group for _, group in sorted_ir_groups]

    if next_state == "finished":
        # Flatten all chunks back to an ordered dict (preserving document order)
        # so ir_grouper can rebuild formatted_str and ir_join from the
        # LLM-updated IRChunk.category values.
        flat: dict[str, IRChunk] = {}
        for group in groups:
            for chunk_id, chunk in zip(group.ir_chunk_ids, group.ir_chunks):
                # Clear article/paragraph numbering on non-조문 chunks so they
                # don't pollute grouping (e.g. a 제목 chunk that was initially
                # misdetected as 조문 would still carry stale article_n).
                if chunk.category != "조문":
                    chunk = chunk.model_copy(update={"article_n": [], "paragraph_n": []})
                flat[chunk_id] = chunk
        groups = ir_grouper(flat)

    return {"ir_groups": groups, "ir_groups_temp": [], "preprocess_state": next_state}

###################################################################################################

def prelim_categorization_node_worker(state: IRGroupState):
    # Groups without a detected article number are very likely non-조문 (title, preamble, signature, etc.)
    # Skip the LLM call and leave them as uncategorized for the detailed pass.
    if state.ir_group.article_n == "-1":
        print(f"\n--- PRELIM SKIP (group {state.group_idx}, article_n=-1) → uncategorized\n")
        return {"ir_groups_temp": [(state.group_idx, state.ir_group)]}

    # Skip groups with empty content
    if not state.ir_group.formatted_str.strip():
        print(f"\n--- PRELIM SKIP (group {state.group_idx}, empty) → uncategorized\n")
        return {"ir_groups_temp": [(state.group_idx, state.ir_group)]}

    messages = [
        ("system", prompts["prelim_categorization"]),
        ("user", state.ir_group.formatted_str)
    ]
    print(f"\n--- LLM INPUT (group {state.group_idx})")
    reply = TextPrelimCategorization.model_validate(prelim_categorizer_llm.invoke(messages))
    print(f"\n--- LLM OUTPUT (group {state.group_idx}) ---\n{reply!r}\n")


    updated_chunks = []
    for chunk in state.ir_group.ir_chunks:
        new_chunk = chunk.model_copy(update={"category": reply.category})
        updated_chunks.append(new_chunk)

    new_ir_group = state.ir_group.model_copy(update={"ir_chunks": updated_chunks})

    return {"ir_groups_temp": [(state.group_idx, new_ir_group)]}


def categorization_node_worker(state: IRGroupState):

    def para_key(chunk_id: str) -> str:
        return re.sub(r"\.r\d+$", "", chunk_id)

    # Group chunk indices and accumulate text by paragraph key
    para_indices: dict[str, list[int]] = {}
    para_texts: dict[str, str] = {}

    for i, (chunk_id, chunk) in enumerate(zip(state.ir_group.ir_chunk_ids, state.ir_group.ir_chunks)):
        key = para_key(chunk_id)
        para_indices.setdefault(key, []).append(i)
        para_texts[key] = para_texts.get(key, "") + chunk.text

    # Classify paragraphs that contain at least one uncategorized chunk
    para_categories: dict[str, str] = {}
    for key, indices in para_indices.items():
        if not any(state.ir_group.ir_chunks[i].category == "uncategorized" for i in indices):
            continue
        text = para_texts[key].strip()
        if not text:
            para_categories[key] = "빈칸"
            continue
        messages = [
            ("system", prompts["categorization"]),
            ("user", text)
        ]
        print(f"\n--- LLM INPUT (group {state.group_idx}, para {key}) ---\n{text}\n")
        reply = TextCategorization.model_validate(categorizer_llm.invoke(messages))
        print(f"\n--- LLM OUTPUT (group {state.group_idx}, para {key}) ---\n{reply!r}\n")
        para_categories[key] = reply.category

    # Apply categories back; default tbl chunks to "기타"
    updated_chunks = list(state.ir_group.ir_chunks)
    for key, indices in para_indices.items():
        if key in para_categories:
            for i in indices:
                updated_chunks[i] = updated_chunks[i].model_copy(update={"category": para_categories[key]})

    new_ir_group = state.ir_group.model_copy(update={"ir_chunks": updated_chunks})
    return {"ir_groups_temp": [(state.group_idx, new_ir_group)]}

###################################################################################################

parser_graph_builder = StateGraph(DocumentState)

parser_graph_builder.add_node("prelim_categorization_workers", prelim_categorization_node_worker)
parser_graph_builder.add_node("categorization_workers", categorization_node_worker)
parser_graph_builder.add_node("document_reducer", document_reducer)

_splitter_targets = ["prelim_categorization_workers", "categorization_workers", END]
parser_graph_builder.add_conditional_edges(START, document_splitter, _splitter_targets)
parser_graph_builder.add_edge("prelim_categorization_workers", "document_reducer")
parser_graph_builder.add_conditional_edges("document_reducer", document_splitter, _splitter_targets)
parser_graph_builder.add_edge("categorization_workers", "document_reducer")

parser_graph = parser_graph_builder.compile()
