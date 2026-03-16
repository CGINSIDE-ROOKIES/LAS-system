from pydantic import BaseModel, Field, ValidationError, computed_field

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from hwpx import HwpxDocument
from ir import create_ir_dict, ir_grouper
from las_types import IRGroup

from pathlib import Path
from typing import Literal, Annotated, Any, cast
import operator

from prompts import get_prompts
from env_loader import load_env_SecretStr, load_env_str

prompts = get_prompts()

"""
Reasoning과 관련해서, 이 필드를 CoT간접 유도를 위해서 저걸 먼저 생성하도록 유도가 필요
프롬팅에서 하던지 아니면 시스템적으로 할 수 있는건지?
"""

class TextPrelimCategorization(BaseModel):
    """"""
    reasoning: str = Field(
        description="이렇게 분류한 간단한 이유 한줄."
    )
    category: Literal["조문", "uncategorized"] = Field(
        description="이 텍스트의 분류, 하나만 고르세요."
    )


class TextCategorization(BaseModel):
    """"""
    reasoning: str = Field(
        description="이렇게 분류한 간단한 이유 한줄. 여기를 먼저 채워넣으세요!"
    )
    category: Literal["제목", "전문", "입력란", "기타"] = Field(
        description="이 텍스트의 분류, 하나만 고르세요."
    )

llm = ChatOpenAI(
    base_url=load_env_str("PARSER_LLM_URL"),
    api_key=load_env_SecretStr("PARSER_LLM_KEY"),
    model=load_env_str("PARSER_LLM_MODEL", ""),
)

prelim_categorizer_llm = llm.with_structured_output(TextPrelimCategorization, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError), stop_after_attempt=3)
categorizer_llm = llm.with_structured_output(TextCategorization, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError), stop_after_attempt=3)

class DocumentState(BaseModel):  # Main graph state
    target_file: Path = Field(default=Path())  # kind temp.
    ir_groups: list[IRGroup] = Field(default=[])
    
    # doc may hold other doctype isntances, also due to serialization issues, not used
    # doc: Any = Field(default=None)  # HwpxDocument
    
    # used as a collector (for concurrent workers) before re-indexing
    ir_groups_temp: Annotated[list[tuple[int, IRGroup]], operator.add] = \
        Field(default=[])

    @computed_field
    def formatted_content(self) -> list[str]:
        assert self.ir_groups, "ir_groups needs to be inserted/generated!"
        return [grp.formatted_str for grp in self.ir_groups]
    
    @classmethod
    def from_hwpx(cls, file_path: Path):
        with HwpxDocument.open(file_path) as doc:
            ir_mappings = create_ir_dict(doc)
            ir_groups = ir_grouper(ir_mappings)
            return cls(
                target_file=file_path,
                ir_groups=ir_groups,
            )
    
    @classmethod
    def from_hwp(cls, file_path: Path):
        # convert hwp to hwpx and then invoke from_hwpx
        ...
    
    @classmethod
    def from_docx(cls, file_path: Path):
        ...
    
    @classmethod
    def from_pdf(cls, file_path: Path):
        # exact mapping to OOXML Xpath (that the IR uses for ID) is not possible
        # needs a custom translator to at least mimick the translation
        ...


class IRGroupState(BaseModel):
    # IRGroup is put in a list and order should be maintained... 
    # (needs design change for that or doesn't matter? 흠...)
    group_idx: int
    ir_group: IRGroup


def document_splitter(state: DocumentState):
    return [Send("prelim_workers", IRGroupState(group_idx=i, ir_group=ir_group))
            for i, ir_group in enumerate(state.ir_groups)]


def document_reducer(state: DocumentState):
    # ir_groups_temp needs to be cleared!!! (or it'll accumulate)
    sorted_ir_groups = sorted(state.ir_groups_temp, key=lambda x: x[0])
    return {"ir_groups": [group for _, group in sorted_ir_groups], "ir_groups_temp": []}

#####################################################################

def prelim_categorization_node_worker(state: IRGroupState):
    messages = [
        ("system", prompts["prelim_categorization"]),
        ("user", state.ir_group.formatted_str)
    ]
    print(f"\n--- LLM INPUT (group {state.group_idx}) ---\n{messages[1][1]}\n")
    reply = TextPrelimCategorization.model_validate(prelim_categorizer_llm.invoke(messages))
    print(f"\n--- LLM OUTPUT (group {state.group_idx}) ---\n{reply!r}\n")
    
    updated_chunks = []
    for chunk in state.ir_group.ir_chunks:
        new_chunk = chunk.model_copy(update={"category": reply.category}) 
        updated_chunks.append(new_chunk)
        
    new_ir_group = state.ir_group.model_copy(update={"ir_chunks": updated_chunks})
    
    return {"ir_groups_temp": [(state.group_idx, new_ir_group)]}

#####################################################################

worker_graph_builder = StateGraph(IRGroupState)
main_graph_builder = StateGraph(DocumentState)

main_graph_builder.add_node("prelim_workers", prelim_categorization_node_worker)
main_graph_builder.add_node("document_reducer", document_reducer)

main_graph_builder.add_conditional_edges(START, document_splitter)
main_graph_builder.add_edge("prelim_workers", "document_reducer")
main_graph_builder.add_edge("document_reducer", END)

main_graph = main_graph_builder.compile()


file_path = "/home/maxjo/Work/python-hwpx/tests_new/input/07_청소년_대중문화예술인_또는_연습생_표준_부속합의서.hwpx"
result = main_graph.invoke(
    input=DocumentState.from_hwpx(Path(file_path)),
    config={"max_concurrency": 1}
)

for group in result["ir_groups"]:
    group = cast(IRGroup, group)
    for chunk in group.ir_chunks:
        text = chunk.markdown_text
        category = chunk.category
        print(f"category: {category}\nchunk: {text}\n==========\n")
