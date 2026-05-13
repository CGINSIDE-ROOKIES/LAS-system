from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
from typing import Any

import psycopg2.extensions
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from doc_processor.api import TextEdit, apply_document_edits, parse_document
from doc_processor.contract_review import (
    ClauseReviewResult,
    ContractReviewConfig,
    ContractReviewGraphState,
    ContractReviewHumanDecision,
    ContractReviewResult,
    build_contract_review_graph,
)

from src.db import db_connection
from src.dependencies import get_generation_service, get_rag_pipeline

from . import previews, storage
from .models import (
    ApplyDocumentReviewResponse,
    DocumentReviewOptions,
    ResumeDocumentReviewResponse,
)

logger = logging.getLogger(__name__)

_CHECKPOINTER = InMemorySaver()
_GRAPH = build_contract_review_graph(checkpointer=_CHECKPOINTER)
_GRAPH_LOCK = threading.RLock()
_RISK_ORDER = {"none": 0, "low": 1, "mid": 2, "high": 3, "crit": 4}


class DocumentReviewServiceError(Exception):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def run_document_review_job(review_id: str, options_payload: dict[str, Any]) -> None:
    started_at = time.perf_counter()
    options = DocumentReviewOptions.model_validate(options_payload)
    logger.info(
        "document review job started: review_id=%s options=%s storage_root=%s",
        review_id,
        _log_options(options),
        storage.storage_root(),
    )
    try:
        with db_connection() as conn:
            job = _require_job(conn, review_id)
            original_path = Path(job["original_artifact_path"])
            _save_original_preview(conn, review_id, original_path)
            logger.info(
                "document review original preview saved: review_id=%s source=%s preview=%s",
                review_id,
                original_path,
                storage.parser_preview_path_for(review_id),
            )
            storage.update_job(
                conn,
                review_id,
                status="running",
                stage="parser_started",
                progress=0.10,
                error=None,
            )
            storage.add_event(
                conn,
                review_id,
                "parser_started",
                {"progress": 0.10, "preview_url": _preview_url(review_id)},
            )

        parse_started_at = time.perf_counter()
        parse_result = parse_document(
            source_path=original_path,
            relevance_mode=options.relevance_mode,
            boundary_review_enabled=options.boundary_review_enabled,
            label_review_enabled=options.label_review_enabled,
            max_concurrent_workers=options.parser_max_concurrent_workers,
            llm_repair_max_attempts=options.parser_llm_repair_max_attempts,
            prompt_profile=options.prompt_profile,
            include_paragraphs=True,
            include_clauses=True,
            include_editable_targets=False,
            max_paragraphs=None,
            paragraph_excerpt_length=None,
        )
        logger.info(
            "document review parser completed: review_id=%s elapsed=%.2fs accepted=%s source_doc_type=%s clauses=%s subclauses=%s errors=%s",
            review_id,
            time.perf_counter() - parse_started_at,
            getattr(parse_result, "accepted", None),
            getattr(parse_result, "source_doc_type", None),
            getattr(parse_result, "clause_count", None),
            getattr(parse_result, "subclause_count", None),
            len(getattr(parse_result, "errors", None) or []),
        )

        parser_html = previews.render_parser_preview(original_path, parse_result)
        parser_preview_path = storage.parser_preview_path_for(review_id)
        parser_preview_path.write_text(parser_html, encoding="utf-8")

        with db_connection() as conn:
            storage.update_job(
                conn,
                review_id,
                status="running",
                stage="parser_completed",
                progress=0.35,
                source_doc_type=parse_result.source_doc_type,
                parser_result=parse_result.model_dump(mode="json"),
                current_preview_kind="parser",
            )
            storage.upsert_artifact(
                conn,
                review_id=review_id,
                kind="parser_preview",
                path=str(parser_preview_path),
                content_type="text/html; charset=utf-8",
            )
            storage.add_event(
                conn,
                review_id,
                "parser_completed",
                {
                    "progress": 0.35,
                    "clause_count": parse_result.clause_count,
                    "subclause_count": parse_result.subclause_count,
                    "preview_url": _preview_url(review_id),
                },
            )
            storage.update_job(conn, review_id, stage="review_started", progress=0.40)
            storage.add_event(conn, review_id, "review_started", {"progress": 0.40})

        review_started_at = time.perf_counter()
        review_result, interrupted = _run_review_graph(
            review_id=review_id,
            original_path=original_path,
            parse_result=parse_result,
            options=options,
        )
        logger.info(
            "document review graph completed: review_id=%s elapsed=%.2fs interrupted=%s clause_reviews=%s findings=%s hitl_requests=%s risk_counts=%s",
            review_id,
            time.perf_counter() - review_started_at,
            interrupted,
            len(review_result.clause_reviews),
            len(review_result.findings),
            len(review_result.hitl_requests),
            review_result.clause_risk_counts,
        )

        risk_html = previews.render_risk_preview(original_path, review_result)
        risk_preview_path = storage.risk_preview_path_for(review_id)
        risk_preview_path.write_text(risk_html, encoding="utf-8")

        reviewed_clauses = len(review_result.clause_reviews)
        total_clauses = max(reviewed_clauses, len(parse_result.clauses), 1)
        status = "hitl_waiting" if interrupted else "completed"
        stage = "hitl_waiting" if interrupted else "completed"
        progress = 0.80 if interrupted else 1.0
        with db_connection() as conn:
            storage.update_job(
                conn,
                review_id,
                status=status,
                stage=stage,
                progress=progress,
                contract_review_result=review_result.model_dump(mode="json"),
                current_preview_kind="risk",
            )
            storage.upsert_artifact(
                conn,
                review_id=review_id,
                kind="risk_preview",
                path=str(risk_preview_path),
                content_type="text/html; charset=utf-8",
            )
            storage.save_suggestions_from_result(conn, review_id, review_result)
            storage.add_event(
                conn,
                review_id,
                "review_progress",
                {
                    "progress": progress,
                    "reviewed_clauses": reviewed_clauses,
                    "total_clauses": total_clauses,
                    "preview_url": _preview_url(review_id),
                },
            )
            if interrupted:
                storage.add_event(
                    conn,
                    review_id,
                    "hitl_waiting",
                    {
                        "progress": progress,
                        "finding_count": len(review_result.findings),
                        "request_count": len(review_result.hitl_requests),
                        "suggestions_url": _suggestions_url(review_id),
                    },
                )
            else:
                storage.add_event(
                    conn,
                    review_id,
                    "completed",
                    {"progress": 1.0, "preview_url": _preview_url(review_id)},
                )
        logger.info(
            "document review job finished: review_id=%s status=%s stage=%s elapsed=%.2fs findings=%s",
            review_id,
            status,
            stage,
            time.perf_counter() - started_at,
            len(review_result.findings),
        )
    except Exception as exc:
        logger.exception(
            "document review job failed: review_id=%s elapsed=%.2fs error=%s",
            review_id,
            time.perf_counter() - started_at,
            exc,
        )
        _mark_failed(review_id, exc)


def resume_document_review(
    conn: psycopg2.extensions.connection,
    review_id: str,
) -> ResumeDocumentReviewResponse:
    job = _require_job(conn, review_id)
    if job["status"] != "hitl_waiting":
        raise DocumentReviewServiceError(409, "Review is not waiting for HITL decisions.")

    decisions = storage.resume_decisions(conn, review_id)
    if not decisions:
        raise DocumentReviewServiceError(400, "No accepted, rejected, or feedback decisions to resume with.")

    options = DocumentReviewOptions.model_validate(job.get("options") or {})
    logger.info(
        "document review resume requested: review_id=%s decisions=%s status=%s stage=%s",
        review_id,
        len(decisions),
        job["status"],
        job["stage"],
    )
    storage.update_job(conn, review_id, status="running", stage="review_progress", progress=0.82)
    storage.add_event(conn, review_id, "review_progress", {"progress": 0.82, "hitl_resume_started": True})

    try:
        with _GRAPH_LOCK:
            output = _GRAPH.invoke(
                Command(resume={"decisions": decisions}),
                config=_graph_config(review_id, options),
            )
        state = ContractReviewGraphState.model_validate(output)
        if state.result is None:
            raise ValueError("Contract review graph did not return a resumed result.")
        result = ContractReviewResult.model_validate(state.result)
    except Exception:
        logger.warning(
            "Falling back to persisted contract review result for HITL resume: review_id=%s",
            review_id,
            exc_info=True,
        )
        stored_result = job.get("contract_review_result")
        if not stored_result:
            raise DocumentReviewServiceError(409, "Review checkpoint is no longer available.")
        result = _apply_decisions_to_result(ContractReviewResult.model_validate(stored_result), decisions)

    has_accepted_edit = any(
        finding.status == "accepted" and finding.proposed_edit is not None
        for finding in result.findings
    )
    next_status = "running" if has_accepted_edit else "completed"
    next_stage = "review_progress" if has_accepted_edit else "completed"
    next_progress = 0.82 if has_accepted_edit else 1.0

    storage.update_job(
        conn,
        review_id,
        status=next_status,
        stage=next_stage,
        progress=next_progress,
        contract_review_result=result.model_dump(mode="json"),
    )
    storage.save_suggestions_from_result(conn, review_id, result)
    storage.add_event(
        conn,
        review_id,
        "review_progress",
        {"progress": next_progress, "decisions_applied": len(decisions)},
    )
    if next_status == "completed":
        storage.add_event(
            conn,
            review_id,
            "completed",
            {"progress": 1.0, "preview_url": _preview_url(review_id)},
        )
    logger.info(
        "document review resume completed: review_id=%s decisions=%s next_status=%s next_stage=%s accepted_edit=%s",
        review_id,
        len(decisions),
        next_status,
        next_stage,
        has_accepted_edit,
    )
    return ResumeDocumentReviewResponse(
        review_id=review_id,
        status=next_status,
        stage=next_stage,
        decisions_applied=len(decisions),
    )


def apply_document_review(
    conn: psycopg2.extensions.connection,
    review_id: str,
) -> ApplyDocumentReviewResponse:
    job = _require_job(conn, review_id)
    if job["status"] in {"queued", "failed", "applying"}:
        raise DocumentReviewServiceError(409, f"Review status {job['status']!r} cannot be applied.")

    rows = storage.accepted_suggestions(conn, review_id)
    edits, skipped_conflicts = _accepted_edits(rows)
    if not edits:
        raise DocumentReviewServiceError(400, "No accepted suggestions with proposed edits are available.")

    source_name = job["source_name"]
    original_path = Path(job["original_artifact_path"])
    edited_path = storage.edited_path_for(review_id, source_name)
    logger.info(
        "document review apply requested: review_id=%s accepted_rows=%s edit_count=%s skipped_conflicts=%s source=%s output=%s",
        review_id,
        len(rows),
        len(edits),
        skipped_conflicts,
        original_path,
        edited_path,
    )
    storage.update_job(conn, review_id, status="applying", stage="apply_started", progress=0.85)
    storage.add_event(conn, review_id, "apply_started", {"progress": 0.85, "edit_count": len(edits)})
    conn.commit()

    try:
        result = apply_document_edits(
            source_path=original_path,
            edits=edits,
            output_path=str(edited_path),
        )
    except Exception as exc:
        logger.exception("document review apply failed: review_id=%s error=%s", review_id, exc)
        storage.update_job(
            conn,
            review_id,
            status="failed",
            stage="failed",
            error=str(exc),
        )
        storage.add_event(conn, review_id, "failed", {"progress": 0.85, "error": str(exc)})
        conn.commit()
        raise

    if not result.ok:
        payload = result.model_dump(mode="json")
        logger.warning(
            "document review apply validation failed: review_id=%s validation=%s warnings=%s",
            review_id,
            payload.get("validation"),
            payload.get("warnings"),
        )
        storage.update_job(
            conn,
            review_id,
            status="failed",
            stage="failed",
            error="Accepted edits could not be applied.",
        )
        storage.add_event(conn, review_id, "failed", {"progress": 0.85, "validation": payload.get("validation")})
        conn.commit()
        raise DocumentReviewServiceError(422, payload)

    edited_html = previews.render_edited_preview(result.output_path or edited_path, edits)
    edited_preview_path = storage.edited_preview_path_for(review_id)
    edited_preview_path.write_text(edited_html, encoding="utf-8")

    output_path = str(result.output_path or edited_path)
    storage.update_job(
        conn,
        review_id,
        status="completed",
        stage="completed",
        progress=1.0,
        edited_artifact_path=output_path,
        current_preview_kind="edited",
        error=None,
    )
    storage.upsert_artifact(
        conn,
        review_id=review_id,
        kind="edited",
        path=output_path,
        content_type=storage.content_type_for_path(output_path),
    )
    storage.upsert_artifact(
        conn,
        review_id=review_id,
        kind="edited_preview",
        path=str(edited_preview_path),
        content_type="text/html; charset=utf-8",
    )
    storage.add_event(
        conn,
        review_id,
        "apply_completed",
        {
            "progress": 0.95,
            "edits_applied": result.edits_applied,
            "download_url": _download_url(review_id),
            "preview_url": _preview_url(review_id),
        },
    )
    storage.add_event(
        conn,
        review_id,
        "completed",
        {
            "progress": 1.0,
            "download_url": _download_url(review_id),
            "preview_url": _preview_url(review_id),
        },
    )
    logger.info(
        "document review apply completed: review_id=%s edits_applied=%s warnings=%s output=%s",
        review_id,
        result.edits_applied,
        list(result.warnings),
        output_path,
    )
    return ApplyDocumentReviewResponse(
        review_id=review_id,
        status="completed",
        stage="completed",
        edits_applied=result.edits_applied,
        skipped_conflicts=skipped_conflicts,
        download_url=_download_url(review_id),
        preview_url=_preview_url(review_id),
        warnings=list(result.warnings),
    )


def _run_review_graph(
    *,
    review_id: str,
    original_path: Path,
    parse_result: Any,
    options: DocumentReviewOptions,
) -> tuple[ContractReviewResult, bool]:
    graph_state = ContractReviewGraphState(
        parse_result=parse_result,
        config=_contract_config(options),
        render_source_path=str(original_path),
    )
    with _GRAPH_LOCK:
        output = _GRAPH.invoke(graph_state, config=_graph_config(review_id, options))
    interrupted = "__interrupt__" in output
    state = ContractReviewGraphState.model_validate(output)
    if state.result is None:
        raise ValueError("Contract review graph did not produce a result.")
    return ContractReviewResult.model_validate(state.result), interrupted


def _contract_config(options: DocumentReviewOptions) -> ContractReviewConfig:
    return ContractReviewConfig(
        top_k=options.top_k,
        max_clauses=options.max_clauses,
        max_clause_chars=options.max_clause_chars,
        max_source_text_chars=options.max_source_text_chars,
        max_sources_per_finding=options.max_sources_per_finding,
        max_concurrent_risk_reviews=options.max_concurrent_risk_reviews,
        max_generation_repair_attempts=options.max_generation_repair_attempts,
        max_generation_provider_retry_attempts=options.max_generation_provider_retry_attempts,
        generation_provider_retry_base_delay_sec=options.generation_provider_retry_base_delay_sec,
        doc_types=options.doc_types,
        law_names=options.law_names,
        include_review_html=options.include_review_html,
        review_title=options.review_title,
        pause_for_hitl=True,
        hitl_min_risk_level=options.hitl_min_risk_level,
    )


def _graph_config(review_id: str, options: DocumentReviewOptions) -> dict[str, Any]:
    return {
        "max_concurrency": options.max_concurrent_risk_reviews,
        "configurable": {
            "thread_id": review_id,
            "rag_client": get_rag_pipeline(),
            "generation_client": get_generation_service(),
        },
    }


def _log_options(options: DocumentReviewOptions) -> dict[str, Any]:
    return {
        "relevance_mode": str(options.relevance_mode),
        "boundary_review_enabled": options.boundary_review_enabled,
        "label_review_enabled": options.label_review_enabled,
        "parser_max_concurrent_workers": options.parser_max_concurrent_workers,
        "top_k": options.top_k,
        "max_clauses": options.max_clauses,
        "max_concurrent_risk_reviews": options.max_concurrent_risk_reviews,
        "max_generation_repair_attempts": options.max_generation_repair_attempts,
        "hitl_min_risk_level": options.hitl_min_risk_level,
    }


def _accepted_edits(rows: list[dict[str, Any]]) -> tuple[list[TextEdit], list[str]]:
    accepted: list[tuple[dict[str, Any], TextEdit]] = []
    for row in rows:
        proposed_edit = row.get("proposed_edit")
        if not proposed_edit:
            continue
        accepted.append((row, TextEdit.model_validate(proposed_edit)))

    accepted.sort(key=lambda item: (-_RISK_ORDER.get(str(item[0].get("risk_level") or "none"), 0), item[0]["finding_id"]))
    edits: list[TextEdit] = []
    skipped_conflicts: list[str] = []
    seen_targets: set[tuple[str, str]] = set()
    for row, edit in accepted:
        key = (str(edit.target_kind), edit.target_id)
        if key in seen_targets:
            skipped_conflicts.append(str(row["finding_id"]))
            continue
        seen_targets.add(key)
        edits.append(edit)
    return edits, skipped_conflicts


def _save_original_preview(
    conn: psycopg2.extensions.connection,
    review_id: str,
    original_path: Path,
) -> None:
    preview_path = storage.parser_preview_path_for(review_id)
    if not preview_path.exists():
        preview_path.write_text(previews.render_original_preview(original_path), encoding="utf-8")
    storage.upsert_artifact(
        conn,
        review_id=review_id,
        kind="parser_preview",
        path=str(preview_path),
        content_type="text/html; charset=utf-8",
    )
    storage.update_job(conn, review_id, current_preview_kind="parser")


def _apply_decisions_to_result(
    result: ContractReviewResult,
    decisions: list[dict[str, Any]],
) -> ContractReviewResult:
    typed_decisions = [ContractReviewHumanDecision.model_validate(decision) for decision in decisions]
    status_by_id = {
        decision.finding_id: _status_from_action(decision.action)
        for decision in typed_decisions
    }
    findings = [
        finding.model_copy(update={"status": status_by_id.get(finding.finding_id, finding.status)})
        for finding in result.findings
    ]
    findings_by_clause: dict[str, list[Any]] = {}
    for finding in findings:
        findings_by_clause.setdefault(finding.clause_id, []).append(finding)
    clause_reviews = [
        ClauseReviewResult.model_validate(review).model_copy(
            update={"findings": findings_by_clause.get(review.clause_id, [])}
        )
        for review in result.clause_reviews
    ]
    return result.model_copy(
        update={
            "findings": findings,
            "clause_reviews": clause_reviews,
            "human_decisions": typed_decisions,
        }
    )


def _status_from_action(action: str) -> str:
    if action == "accept":
        return "accepted"
    if action == "reject":
        return "rejected"
    return "feedback"


def _require_job(conn: psycopg2.extensions.connection, review_id: str) -> dict[str, Any]:
    job = storage.get_job(conn, review_id)
    if job is None:
        raise DocumentReviewServiceError(404, "Document review not found.")
    return job


def _mark_failed(review_id: str, exc: Exception) -> None:
    try:
        with db_connection() as conn:
            job = storage.get_job(conn, review_id)
            progress = max(float((job or {}).get("progress") or 0.05), 0.10)
            storage.update_job(
                conn,
                review_id,
                status="failed",
                stage="failed",
                progress=progress,
                error=str(exc),
            )
            storage.add_event(
                conn,
                review_id,
                "failed",
                {
                    "progress": progress,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
    except Exception:
        logger.exception("failed to persist document review failure: review_id=%s", review_id)


def _preview_url(review_id: str) -> str:
    return f"/api/v1/document-reviews/{review_id}/preview.html?kind=latest"


def _suggestions_url(review_id: str) -> str:
    return f"/api/v1/document-reviews/{review_id}/suggestions"


def _download_url(review_id: str) -> str:
    return f"/api/v1/document-reviews/{review_id}/download"
