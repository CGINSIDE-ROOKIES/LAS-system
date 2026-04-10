from __future__ import annotations

from pathlib import Path

from langgraph.graph import END
from langgraph.types import Command, Send

from document_processor import DocIR

from ..logging_utils import log_info
from ..observability import traced_phase1_node
from ..state import WorkflowState
from ..types import Phase1Analysis, Phase1DocumentMeta, Phase1Result, RelevanceDecision, RelevanceMode, WorkflowDelta, WorkflowMeta
from .boundaries import BoundaryReviewOutput, apply_boundary_reviews, detect_boundary_suspects, review_single_boundary_suspect_with_llm
from .converters import annotate_doc_with_phase1
from .labels import LabelReviewOutput, apply_label_reviews, label_paragraphs, review_single_ambiguous_label_with_llm
from .parser import build_clause_entries_from_analysis, parse_document_structure
from .relevance import needs_llm_relevance_review, review_relevance_with_llm, score_relevance


def _coerce_state(state: WorkflowState | dict) -> WorkflowState:
    return state if isinstance(state, WorkflowState) else WorkflowState.model_validate(state)


@traced_phase1_node("phase1.load_document")
def load_document(state: WorkflowState) -> Command[str]:
    if state.working_doc is not None and state.base_doc is not None:
        return Command(goto="screen_relevance")
    if state.working_doc is not None:
        return Command(update={"base_doc": state.working_doc}, goto="screen_relevance")
    if state.base_doc is not None:
        return Command(update={"working_doc": state.base_doc}, goto="screen_relevance")
    if state.target_file is None:
        raise ValueError("WorkflowState.target_file or base_doc/working_doc is required.")

    doc = DocIR.from_file(Path(state.target_file))
    return Command(update={"base_doc": doc, "working_doc": doc}, goto="screen_relevance")


@traced_phase1_node("phase1.screen_relevance")
def screen_relevance(state: WorkflowState) -> Command[str]:
    if state.working_doc is None:
        raise ValueError("Document must be loaded before relevance screening.")

    config = state.phase1_config
    if config.relevance_mode == RelevanceMode.DISABLED:
        decision = RelevanceDecision(
            mode=config.relevance_mode,
            is_relevant=True,
            reason="Relevance screening disabled by config.",
            doc_kind="contract",
        )
    else:
        decision = score_relevance(state.working_doc, config)
        if needs_llm_relevance_review(decision, config):
            try:
                decision = review_relevance_with_llm(state.working_doc, config, keyword_decision=decision)
            except Exception as exc:  # pragma: no cover - external model failures are environment-dependent
                decision.reason = f"{decision.reason} LLM fallback skipped: {exc}"

    analysis = state.phase1_analysis.model_copy(deep=True) if state.phase1_analysis is not None else Phase1Analysis()
    analysis.relevance = decision
    updates = {"phase1_analysis": analysis}

    if not decision.is_relevant:
        result = Phase1Result(
            accepted=False,
            reason=decision.reason,
            relevance=decision,
            notes=["Document rejected during relevance screening."],
        )
        updates["phase1_result"] = result
        return Command(update=updates, goto="finalize_phase1")

    return Command(update=updates, goto="detect_numbering_rules")


@traced_phase1_node("phase1.detect_numbering_rules")
def detect_numbering_rules(state: WorkflowState) -> Command[str]:
    if state.working_doc is None:
        raise ValueError("Document must be loaded before numbering detection.")
    analysis = parse_document_structure(state.working_doc)
    if state.phase1_analysis and state.phase1_analysis.relevance is not None:
        analysis.relevance = state.phase1_analysis.relevance
    return Command(update={"phase1_analysis": analysis}, goto="initial_assign_structure")


@traced_phase1_node("phase1.initial_assign_structure")
def initial_assign_structure(state: WorkflowState) -> Command[str]:
    analysis = state.phase1_analysis
    if analysis is None:
        raise ValueError("phase1_analysis is required before structure assignment.")
    if analysis.clause_rule_name is None:
        result = Phase1Result(
            accepted=True,
            reason="No clause numbering rule found; document kept but left structurally unsegmented.",
            relevance=analysis.relevance,
            notes=["No clause numbering rule found in phase 1."],
        )
        return Command(update={"phase1_result": result}, goto="finalize_phase1")
    analysis.notes.append(
        f"Detected clause rule '{analysis.clause_rule_name}'"
        + (f" and subclause rule '{analysis.subclause_rule_name}'." if analysis.subclause_rule_name else ".")
    )
    return Command(update={"phase1_analysis": analysis}, goto="detect_boundary_suspects")


@traced_phase1_node("phase1.detect_boundary_suspects")
def detect_boundary_suspects_node(state: WorkflowState) -> Command[str]:
    analysis = state.phase1_analysis
    if analysis is None:
        raise ValueError("phase1_analysis is required before boundary detection.")
    analysis = detect_boundary_suspects(analysis)
    goto = "review_boundaries_llm" if analysis.boundary_suspect_unit_ids and state.phase1_config.boundary_review_enabled else "label_paragraphs"
    return Command(update={"phase1_analysis": analysis}, goto=goto)


@traced_phase1_node("phase1.review_boundaries_llm")
def review_boundaries_llm(state: WorkflowState) -> Command[str | Send]:
    if state.working_doc is None or state.phase1_analysis is None:
        raise ValueError("Document and analysis are required before boundary review.")
    suspect_ids = list(state.phase1_analysis.boundary_suspect_unit_ids)
    if not suspect_ids:
        return Command(goto="apply_boundary_resolution")
    log_info(
        state.phase1_config,
        "[phase1.review_boundaries_llm] dispatching %s workers (max_concurrency=%s)",
        len(suspect_ids),
        state.phase1_config.max_concurrent_workers,
    )
    return Command(
        goto=[
            Send(
                "boundary_review_worker",
                {
                    "working_doc": state.working_doc,
                    "phase1_analysis": state.phase1_analysis,
                    "phase1_config": state.phase1_config,
                    "active_review_unit_id": unit_id,
                },
            )
            for unit_id in suspect_ids
        ]
    )


@traced_phase1_node("phase1.review_boundaries_llm.worker")
def boundary_review_worker(state: WorkflowState) -> Command[str]:
    state = _coerce_state(state)
    if state.working_doc is None or state.phase1_analysis is None or state.active_review_unit_id is None:
        raise ValueError("Boundary review worker requires document, analysis, and active_review_unit_id.")
    unit_id = state.active_review_unit_id
    try:
        review = review_single_boundary_suspect_with_llm(
            state.working_doc,
            state.phase1_analysis,
            unit_id,
            state.phase1_config,
        )
    except Exception as exc:  # pragma: no cover
        log_info(state.phase1_config, "[phase1.review_boundaries_llm.worker] unit=%s failed", unit_id)
        return Command(update={"errors": [f"Boundary LLM review failed for {unit_id}: {exc}"]})
    log_info(state.phase1_config, "[phase1.review_boundaries_llm.worker] unit=%s complete", unit_id)
    return Command(
        update={
            "boundary_review_results": [
                {"unit_id": unit_id, "review": review.model_dump(mode="json")},
            ]
        }
    )


@traced_phase1_node("phase1.apply_boundary_resolution")
def apply_boundary_resolution(state: WorkflowState) -> Command[str]:
    if state.phase1_analysis is None:
        raise ValueError("phase1_analysis is required before applying boundary review.")
    reviews = {
        item["unit_id"]: BoundaryReviewOutput.model_validate(item["review"])
        for item in state.boundary_review_results
    }
    analysis = apply_boundary_reviews(state.phase1_analysis, reviews)
    return Command(update={"phase1_analysis": analysis}, goto="label_paragraphs")


@traced_phase1_node("phase1.label_paragraphs")
def label_paragraphs_node(state: WorkflowState) -> Command[str]:
    analysis = state.phase1_analysis
    if analysis is None:
        raise ValueError("phase1_analysis is required before labeling.")
    analysis = label_paragraphs(analysis)
    goto = "review_labels_llm" if analysis.ambiguous_label_unit_ids and state.phase1_config.label_review_enabled else "build_clause_entries"
    return Command(update={"phase1_analysis": analysis}, goto=goto)


@traced_phase1_node("phase1.review_labels_llm")
def review_labels_llm(state: WorkflowState) -> Command[str | Send]:
    if state.working_doc is None or state.phase1_analysis is None:
        raise ValueError("Document and analysis are required before label review.")
    unit_ids = list(state.phase1_analysis.ambiguous_label_unit_ids)
    if not unit_ids:
        return Command(goto="build_clause_entries")
    log_info(
        state.phase1_config,
        "[phase1.review_labels_llm] dispatching %s workers (max_concurrency=%s)",
        len(unit_ids),
        state.phase1_config.max_concurrent_workers,
    )
    return Command(
        goto=[
            Send(
                "label_review_worker",
                {
                    "working_doc": state.working_doc,
                    "phase1_analysis": state.phase1_analysis,
                    "phase1_config": state.phase1_config,
                    "active_review_unit_id": unit_id,
                },
            )
            for unit_id in unit_ids
        ]
    )


@traced_phase1_node("phase1.review_labels_llm.worker")
def label_review_worker(state: WorkflowState) -> Command[str]:
    state = _coerce_state(state)
    if state.working_doc is None or state.phase1_analysis is None or state.active_review_unit_id is None:
        raise ValueError("Label review worker requires document, analysis, and active_review_unit_id.")
    unit_id = state.active_review_unit_id
    try:
        review = review_single_ambiguous_label_with_llm(
            state.working_doc,
            state.phase1_analysis,
            unit_id,
            state.phase1_config,
        )
    except Exception as exc:  # pragma: no cover
        log_info(state.phase1_config, "[phase1.review_labels_llm.worker] unit=%s failed", unit_id)
        return Command(update={"errors": [f"Label LLM review failed for {unit_id}: {exc}"]})
    log_info(state.phase1_config, "[phase1.review_labels_llm.worker] unit=%s complete", unit_id)
    return Command(
        update={
            "label_review_results": [
                {"unit_id": unit_id, "review": review.model_dump(mode="json")},
            ]
        }
    )


@traced_phase1_node("phase1.build_clause_entries")
def build_clause_entries_node(state: WorkflowState) -> Command[str]:
    if state.phase1_analysis is None:
        raise ValueError("phase1_analysis is required before building clause entries.")
    reviews = {
        item["unit_id"]: LabelReviewOutput.model_validate(item["review"])
        for item in state.label_review_results
    }
    analysis = apply_label_reviews(state.phase1_analysis, reviews)
    analysis.clause_entries = build_clause_entries_from_analysis(analysis.paragraphs)
    return Command(update={"phase1_analysis": analysis}, goto="finalize_phase1")


@traced_phase1_node("phase1.finalize_phase1")
def finalize_phase1(state: WorkflowState) -> Command[str]:
    if state.working_doc is None:
        raise ValueError("Document must be loaded before finalization.")

    if state.phase1_result is not None and not state.phase1_result.accepted:
        finalized_doc = state.working_doc.model_copy(deep=True)
        finalized_doc.meta = WorkflowMeta(
            phase1_doc=Phase1DocumentMeta(
                relevance=state.phase1_result.relevance,
                notes=list(state.phase1_result.notes),
            )
        )
        return Command(
            update={
                "working_doc": finalized_doc,
                "current_version": state.current_version + 1,
                "history": state.history
                + [WorkflowDelta(version=state.current_version + 1, stage="phase1", reason=state.phase1_result.reason)],
            },
            goto=END,
        )

    analysis = state.phase1_analysis or Phase1Analysis()
    finalized_doc = annotate_doc_with_phase1(state.working_doc, analysis)
    subclause_count = sum(len(entry.subclauses) for entry in analysis.clause_entries)
    result = Phase1Result(
        accepted=True,
        reason="Phase 1 clause parsing completed.",
        relevance=analysis.relevance,
        clause_rule_name=analysis.clause_rule_name,
        subclause_rule_name=analysis.subclause_rule_name,
        clause_count=len(analysis.clause_entries),
        subclause_count=subclause_count,
        boundary_suspect_unit_ids=list(analysis.boundary_suspect_unit_ids),
        ambiguous_label_unit_ids=list(analysis.ambiguous_label_unit_ids),
        notes=list(analysis.notes),
    )
    return Command(
        update={
            "working_doc": finalized_doc,
            "phase1_result": result,
            "current_version": state.current_version + 1,
            "history": state.history
            + [WorkflowDelta(version=state.current_version + 1, stage="phase1", reason=result.reason)],
        },
        goto=END,
    )
