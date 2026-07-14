from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..state import WorkflowState
from .nodes import (
    boundary_llm_batch,
    finalize_llm,
    load_document,
    llm_analysis,
    llm_analysis_worker,
    regex_analysis,
    screen_relevance,
)


def build_parser_graph():
    builder = StateGraph(WorkflowState)
    builder.add_node("load_document", load_document)
    builder.add_node("screen_relevance", screen_relevance)
    builder.add_node("regex_analysis", regex_analysis)
    builder.add_node("llm_analysis", llm_analysis)
    builder.add_node("boundary_llm_batch", boundary_llm_batch)
    builder.add_node("llm_analysis_worker", llm_analysis_worker)
    builder.add_node("finalize_llm", finalize_llm)

    builder.add_edge(START, "load_document")
    builder.add_edge("llm_analysis_worker", "llm_analysis")
    builder.add_edge("finalize_llm", END)
    return builder.compile()
