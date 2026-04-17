from __future__ import annotations

from pathlib import Path

from langgraph.graph import END
from langgraph.types import Command, Send

from document_processor import DocIR

from ..logging_utils import log_info
from ..observability import traced_structure_analysis_node
from ..state import WorkflowState
from ..parser_types import ParserAnalysis, ParserDocumentMeta, ParserResult, RelevanceDecision, RelevanceMode, WorkflowDelta, WorkflowMeta
from .boundaries import BoundaryReviewOutput, apply_boundary_reviews, detect_boundary_suspects, review_boundary_suspects_with_llm
from .converters import attach_parser_metadata_to_doc
from .labels import LabelReviewOutput, apply_label_reviews, label_paragraphs, review_single_ambiguous_label_with_llm
from .parser import build_clause_entries_from_analysis, parse_document_structure
from .relevance import needs_llm_relevance_review, review_relevance_with_llm, score_relevance


def _coerce_state(state: WorkflowState | dict) -> WorkflowState:
    return state if isinstance(state, WorkflowState) else WorkflowState.model_validate(state)


def _dispatch_review_tasks(
    state: WorkflowState,
    *,
    review_kind: str,
    unit_ids: list[str],
    analysis: ParserAnalysis | None = None,
) -> Command[str | Send]:
    log_info(
        state.parser_config,
        "[structure_analysis.llm_analysis] dispatching %s %s workers (max_concurrency=%s)",
        len(unit_ids),
        review_kind,
        state.parser_config.max_concurrent_workers,
    )
    return Command(
        update={
            "parser_analysis": analysis or state.parser_analysis,
            "llm_review_stage": review_kind,
        },
        goto=[
            Send(
                "llm_analysis_worker",
                {
                    "working_doc": state.working_doc,
                    "parser_analysis": analysis or state.parser_analysis,
                    "parser_config": state.parser_config,
                    "active_review_unit_id": unit_id,
                    "active_review_kind": review_kind,
                },
            )
            for unit_id in unit_ids
        ],
    )


@traced_structure_analysis_node("structure_analysis.load_document")
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


@traced_structure_analysis_node("structure_analysis.screen_relevance")
def screen_relevance(state: WorkflowState) -> Command[str]:
    if state.working_doc is None:
        raise ValueError("Document must be loaded before relevance screening.")

    config = state.parser_config
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

    analysis = state.parser_analysis.model_copy(deep=True) if state.parser_analysis is not None else ParserAnalysis()
    analysis.relevance = decision
    updates = {"parser_analysis": analysis}

    if not decision.is_relevant:
        result = ParserResult(
            accepted=False,
            reason=decision.reason,
            relevance=decision,
            notes=["Document rejected during relevance screening."],
        )
        updates["parser_result"] = result
        return Command(update=updates, goto="finalize_llm")

    return Command(update=updates, goto="regex_analysis")


@traced_structure_analysis_node("structure_analysis.regex_analysis")
def regex_analysis(state: WorkflowState) -> Command[str]:
    if state.working_doc is None:
        raise ValueError("Document must be loaded before regex analysis.")

    analysis = parse_document_structure(state.working_doc)
    if state.parser_analysis and state.parser_analysis.relevance is not None:
        analysis.relevance = state.parser_analysis.relevance

    if analysis.clause_rule_name is None:
        analysis.notes.append("No clause numbering rule found.")
        result = ParserResult(
            accepted=True,
            reason="No clause numbering rule found; document kept but left structurally unsegmented.",
            relevance=analysis.relevance,
            notes=list(analysis.notes),
        )
        return Command(
            update={"parser_analysis": analysis, "parser_result": result},
            goto="finalize_llm",
        )

    analysis.notes.append(
        f"Detected clause rule '{analysis.clause_rule_name}'"
        + (f" and subclause rule '{analysis.subclause_rule_name}'." if analysis.subclause_rule_name else ".")
    )
    analysis = detect_boundary_suspects(analysis)
    return Command(update={"parser_analysis": analysis}, goto="llm_analysis")


@traced_structure_analysis_node("structure_analysis.llm_analysis")
def llm_analysis(state: WorkflowState) -> Command[str | Send]:
    if state.parser_analysis is None:
        raise ValueError("parser_analysis is required before LLM analysis.")

    analysis = state.parser_analysis
    stage = state.llm_review_stage

    if stage is None:
        suspect_ids = list(analysis.boundary_suspect_unit_ids)
        if suspect_ids and state.parser_config.boundary_review_enabled:
            log_info(
                state.parser_config,
                "[structure_analysis.llm_analysis] dispatching boundary batch review (%s suspects)",
                len(suspect_ids),
            )
            return Command(
                update={"parser_analysis": analysis, "llm_review_stage": "boundary"},
                goto="boundary_llm_batch",
            )

        analysis = label_paragraphs(analysis)
        ambiguous_ids = list(analysis.ambiguous_label_unit_ids)
        if ambiguous_ids and state.parser_config.label_review_enabled:
            return _dispatch_review_tasks(
                state,
                review_kind="label",
                unit_ids=ambiguous_ids,
                analysis=analysis,
            )
        return Command(
            update={"parser_analysis": analysis, "llm_review_stage": None},
            goto="finalize_llm",
        )

    if stage == "boundary":
        reviews = {
            item["unit_id"]: BoundaryReviewOutput.model_validate(item["review"])
            for item in state.boundary_review_results
        }
        analysis = apply_boundary_reviews(analysis, reviews)
        analysis = label_paragraphs(analysis)
        ambiguous_ids = list(analysis.ambiguous_label_unit_ids)
        if ambiguous_ids and state.parser_config.label_review_enabled:
            return _dispatch_review_tasks(
                state,
                review_kind="label",
                unit_ids=ambiguous_ids,
                analysis=analysis,
            )
        return Command(
            update={"parser_analysis": analysis, "llm_review_stage": None},
            goto="finalize_llm",
        )

    if stage == "label":
        reviews = {
            item["unit_id"]: LabelReviewOutput.model_validate(item["review"])
            for item in state.label_review_results
        }
        analysis = apply_label_reviews(analysis, reviews)
        return Command(
            update={"parser_analysis": analysis, "llm_review_stage": None},
            goto="finalize_llm",
        )

    raise ValueError(f"Unsupported llm_review_stage: {stage}")


@traced_structure_analysis_node("structure_analysis.llm_analysis.boundary_batch")
def boundary_llm_batch(state: WorkflowState) -> Command[str]:
    state = _coerce_state(state)
    if state.working_doc is None or state.parser_analysis is None:
        raise ValueError("Boundary batch review requires document and analysis.")

    try:
        reviews = review_boundary_suspects_with_llm(
            state.working_doc,
            state.parser_analysis,
            state.parser_config,
        )
    except Exception as exc:  # pragma: no cover
        log_info(
            state.parser_config,
            "[structure_analysis.llm_analysis.boundary_batch] failed",
        )
        return Command(
            update={"errors": [f"Boundary LLM review failed: {exc}"]},
            goto="llm_analysis",
        )

    log_info(
        state.parser_config,
        "[structure_analysis.llm_analysis.boundary_batch] complete (%s reviews)",
        len(reviews),
    )
    return Command(
        update={
            "boundary_review_results": [
                {"unit_id": unit_id, "review": review.model_dump(mode="json")}
                for unit_id, review in reviews.items()
            ]
        },
        goto="llm_analysis",
    )


@traced_structure_analysis_node("structure_analysis.llm_analysis.worker")
def llm_analysis_worker(state: WorkflowState) -> Command[str]:
    state = _coerce_state(state)
    if state.working_doc is None or state.parser_analysis is None or state.active_review_unit_id is None:
        raise ValueError("Review worker requires document, analysis, and active_review_unit_id.")
    if state.active_review_kind is None:
        raise ValueError("Review worker requires active_review_kind.")

    unit_id = state.active_review_unit_id
    review_kind = state.active_review_kind

    try:
        if review_kind == "label":
            review = review_single_ambiguous_label_with_llm(
                state.working_doc,
                state.parser_analysis,
                unit_id,
                state.parser_config,
            )
            update_key = "label_review_results"
        else:
            raise ValueError(f"Unsupported parallel review kind: {review_kind}")
    except Exception as exc:  # pragma: no cover
        log_info(
            state.parser_config,
            "[structure_analysis.llm_analysis.worker] kind=%s unit=%s failed",
            review_kind,
            unit_id,
        )
        return Command(update={"errors": [f"{review_kind.capitalize()} LLM review failed for {unit_id}: {exc}"]})

    log_info(
        state.parser_config,
        "[structure_analysis.llm_analysis.worker] kind=%s unit=%s complete",
        review_kind,
        unit_id,
    )
    return Command(
        update={
            update_key: [
                {"unit_id": unit_id, "review": review.model_dump(mode="json")},
            ]
        }
    )


@traced_structure_analysis_node("structure_analysis.finalize_llm")
def finalize_llm(state: WorkflowState) -> Command[str]:
    if state.working_doc is None:
        raise ValueError("Document must be loaded before finalization.")

    if state.parser_result is not None and not state.parser_result.accepted:
        finalized_doc = state.working_doc.model_copy(deep=True)
        finalized_doc.meta = WorkflowMeta(
            parser_doc=ParserDocumentMeta(
                relevance=state.parser_result.relevance,
                notes=list(state.parser_result.notes),
            )
        )
        return Command(
            update={
                "working_doc": finalized_doc,
                "current_version": state.current_version + 1,
                "history": state.history
                + [WorkflowDelta(version=state.current_version + 1, stage="parser", reason=state.parser_result.reason)],
            },
            goto=END,
        )

    analysis = state.parser_analysis or ParserAnalysis()
    analysis.clause_entries = build_clause_entries_from_analysis(analysis.paragraphs)
    finalized_doc = attach_parser_metadata_to_doc(state.working_doc, analysis)
    subclause_count = sum(len(entry.subclauses) for entry in analysis.clause_entries)

    if state.parser_result is not None and state.parser_result.accepted:
        result = state.parser_result.model_copy(deep=True)
        result.relevance = analysis.relevance
        result.clause_rule_name = analysis.clause_rule_name
        result.subclause_rule_name = analysis.subclause_rule_name
        result.clause_count = len(analysis.clause_entries)
        result.subclause_count = subclause_count
        result.boundary_suspect_unit_ids = list(analysis.boundary_suspect_unit_ids)
        result.ambiguous_label_unit_ids = list(analysis.ambiguous_label_unit_ids)
        result.notes = list(analysis.notes)
    else:
        result = ParserResult(
            accepted=True,
            reason="Parser clause parsing completed.",
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
            "parser_result": result,
            "current_version": state.current_version + 1,
            "history": state.history
            + [WorkflowDelta(version=state.current_version + 1, stage="parser", reason=result.reason)],
        },
        goto=END,
    )
