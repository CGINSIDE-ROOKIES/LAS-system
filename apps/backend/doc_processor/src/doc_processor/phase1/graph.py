from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..state import WorkflowState
from .nodes import (
    apply_boundary_resolution,
    boundary_review_worker,
    build_clause_entries_node,
    detect_boundary_suspects_node,
    detect_numbering_rules,
    finalize_phase1,
    initial_assign_structure,
    label_paragraphs_node,
    label_review_worker,
    load_document,
    review_boundaries_llm,
    review_labels_llm,
    screen_relevance,
)


def build_phase1_graph():
    builder = StateGraph(WorkflowState)
    builder.add_node("load_document", load_document)
    builder.add_node("screen_relevance", screen_relevance)
    builder.add_node("detect_numbering_rules", detect_numbering_rules)
    builder.add_node("initial_assign_structure", initial_assign_structure)
    builder.add_node("detect_boundary_suspects", detect_boundary_suspects_node)
    builder.add_node("review_boundaries_llm", review_boundaries_llm)
    builder.add_node("boundary_review_worker", boundary_review_worker)
    builder.add_node("apply_boundary_resolution", apply_boundary_resolution)
    builder.add_node("label_paragraphs", label_paragraphs_node)
    builder.add_node("review_labels_llm", review_labels_llm)
    builder.add_node("label_review_worker", label_review_worker)
    builder.add_node("build_clause_entries", build_clause_entries_node)
    builder.add_node("finalize_phase1", finalize_phase1)

    builder.add_edge(START, "load_document")
    builder.add_edge("boundary_review_worker", "apply_boundary_resolution")
    builder.add_edge("label_review_worker", "build_clause_entries")
    builder.add_edge("finalize_phase1", END)
    return builder.compile()
