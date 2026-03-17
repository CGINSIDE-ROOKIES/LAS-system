from pydantic import BaseModel, Field, ValidationError

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from las_types import IRGroup, DocumentState, IRGroupState

from pathlib import Path
from typing import Literal, cast
import re


from prompts import get_prompts
from core.env_loader import load_env_SecretStr, load_env_str

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

llm = ChatOpenAI(
    base_url=load_env_str("PARSER_LLM_URL"),
    api_key=load_env_SecretStr("PARSER_LLM_KEY"),
    model=load_env_str("PARSER_LLM_MODEL"),
)

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
    return {"ir_groups": [group for _, group in sorted_ir_groups], "ir_groups_temp": [], "preprocess_state": next_state}

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

main_graph_builder = StateGraph(DocumentState)

main_graph_builder.add_node("prelim_categorization_workers", prelim_categorization_node_worker)
main_graph_builder.add_node("categorization_workers", categorization_node_worker)
main_graph_builder.add_node("document_reducer", document_reducer)

_splitter_targets = ["prelim_categorization_workers", "categorization_workers", END]
main_graph_builder.add_conditional_edges(START, document_splitter, _splitter_targets)
main_graph_builder.add_edge("prelim_categorization_workers", "document_reducer")
main_graph_builder.add_conditional_edges("document_reducer", document_splitter, _splitter_targets)
main_graph_builder.add_edge("categorization_workers", "document_reducer")

main_graph = main_graph_builder.compile()


if __name__ == "__main__":
    # graph_png = main_graph.get_graph().draw_mermaid_png()
    # with open("tests/graph.png", "wb") as f:
    #     f.write(graph_png)
    # print("Graph diagram saved to graph.png")

    file_dirs_std_labor = list(Path("tests/doc_samples/표준계약서모음(hwp-hwpx)").iterdir())
    file_dirs_std_contracts = list(Path("tests/doc_samples/(노동)표준근로계약서모음").iterdir())
    file_dirs = file_dirs_std_labor + file_dirs_std_contracts
    
    [print(f"{i}. {f.name}") for i, f in enumerate(file_dirs)]
    sel = int(input("select: "))
    file_path = file_dirs[sel]

    result = main_graph.invoke(
        input=DocumentState.from_file(Path(file_path)),
        config={"max_concurrency": 4}
    )

    with open(f"tests/results/{file_path.name}_parser_res.txt", "w", encoding="utf-8") as f:
        for group in result["ir_groups"]:
            group = cast(IRGroup, group)
            for chunk in group.ir_chunks:
                text = chunk.text
                category = chunk.category
                f.write(f"category: {category} - {chunk.article_n}.{chunk.paragraph_n}\nchunk: {text}\n==========\n")
            # text = group.formatted_str
            # category = group.ir_chunks[0].category
            # print(f"category: {category}\nchunk: {text}\n==========\n")
