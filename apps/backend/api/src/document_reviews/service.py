from __future__ import annotations

import difflib
import hashlib
import json
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
_FEEDBACK_REGENERATION_SYSTEM_PROMPT = (
    "You revise Korean contract review fix suggestions. Return only one JSON object. "
    "Do not include markdown or explanatory text."
)


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
                {"preview_url": _preview_url(review_id)},
            )
            storage.add_event(
                conn,
                review_id,
                "parser_progress",
                {"phase": "parse_started", "progress": 0.05},
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
            progress_callback=lambda payload: _emit_parser_progress(review_id, payload),
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
                    "clause_count": parse_result.clause_count,
                    "subclause_count": parse_result.subclause_count,
                    "preview_url": _preview_url(review_id),
                },
            )
            storage.update_job(conn, review_id, stage="review_started", progress=0.40)
            storage.add_event(conn, review_id, "review_started", {})

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
                    {"preview_url": _preview_url(review_id)},
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
    storage.add_event(conn, review_id, "review_progress", {"hitl_resume_started": True})

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
        {"decisions_applied": len(decisions)},
    )
    if next_status == "completed":
        storage.add_event(
            conn,
            review_id,
            "completed",
            {"preview_url": _preview_url(review_id)},
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


def regenerate_feedback_suggestion(
    conn: psycopg2.extensions.connection,
    *,
    review_id: str,
    finding_id: str,
    comment: str,
) -> dict[str, Any] | None:
    job = _require_job(conn, review_id)
    suggestion = storage.get_suggestion(conn, review_id, finding_id)
    if suggestion is None:
        return None

    payload = dict(suggestion.get("payload") or {})
    proposed_edit = dict(suggestion.get("proposed_edit") or {})
    target_id = _feedback_target_id(job, suggestion, proposed_edit)
    target_kind = str(proposed_edit.get("target_kind") or "paragraph")
    current_text = _parser_paragraph_text(job.get("parser_result") or {}, target_id)
    if not target_id or not current_text:
        raise DocumentReviewServiceError(422, "No editable target was available for this finding.")

    prompt = _build_feedback_regeneration_prompt(
        suggestion=suggestion,
        current_text=current_text,
        previous_new_text=str(proposed_edit.get("new_text") or ""),
        comment=comment,
    )
    answer = get_generation_service().generate(prompt, system_prompt=_FEEDBACK_REGENERATION_SYSTEM_PROMPT)
    regenerated = _parse_feedback_regeneration(_generation_answer_text(answer))
    new_text = str(regenerated.get("new_text") or "").strip()
    if not new_text:
        raise DocumentReviewServiceError(422, "Feedback regeneration did not return a replacement text.")
    if new_text == current_text:
        raise DocumentReviewServiceError(422, "Feedback regeneration returned unchanged text.")

    title = str(regenerated.get("title") or suggestion.get("title") or "")
    guidance = str(regenerated.get("guidance") or regenerated.get("reason") or suggestion.get("guidance") or "")
    selected_text = str(regenerated.get("selected_text") or suggestion.get("selected_text") or "")
    updated_edit = {
        "edit_type": "text",
        "target_kind": target_kind,
        "target_id": target_id,
        "expected_text_hash": str(proposed_edit.get("expected_text_hash") or _text_hash(current_text)),
        "new_text": new_text,
        "reason": guidance or title or "Feedback-regenerated contract review suggestion",
    }
    payload.update(
        {
            "title": title,
            "guidance": guidance,
            "recommendation": guidance,
            "selected_text": selected_text,
            "diff": _text_diff(current_text, new_text),
            "last_feedback": _decision_payload("feedback", comment),
            "feedback_regeneration": {
                "status": "completed",
                "comment": comment,
                "previous_new_text": str(proposed_edit.get("new_text") or ""),
            },
        }
    )
    payload.pop("decision", None)
    return storage.update_suggestion_payload_and_edit(
        conn,
        review_id=review_id,
        finding_id=finding_id,
        status="pending",
        payload=payload,
        proposed_edit=updated_edit,
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
    storage.add_event(conn, review_id, "apply_started", {"edit_count": len(edits)})
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
        storage.add_event(conn, review_id, "failed", {"error": str(exc)})
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
        storage.add_event(conn, review_id, "failed", {"validation": payload.get("validation")})
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
    graph_config = _graph_config(review_id, options)
    latest_values: dict[str, Any] | None = None
    interrupted = False
    progress_state: dict[str, Any] = {"processed": 0, "total": None}
    with _GRAPH_LOCK:
        for mode, chunk in _GRAPH.stream(
            graph_state,
            config=graph_config,
            stream_mode=["updates", "values"],
        ):
            if mode == "updates":
                if "__interrupt__" in chunk:
                    interrupted = True
                _emit_review_progress_from_update(review_id, progress_state, chunk)
            elif mode == "values":
                latest_values = chunk
    if latest_values is None:
        raise ValueError("Contract review graph did not produce a final state.")
    interrupted = interrupted or "__interrupt__" in latest_values
    state = ContractReviewGraphState.model_validate(latest_values)
    if state.result is None:
        raise ValueError("Contract review graph did not produce a result.")
    return ContractReviewResult.model_validate(state.result), interrupted


def _emit_parser_progress(review_id: str, payload: dict[str, Any]) -> None:
    try:
        with db_connection() as conn:
            storage.add_event(conn, review_id, "parser_progress", payload)
    except Exception:
        logger.warning(
            "failed to persist parser progress event: review_id=%s payload=%s",
            review_id,
            payload,
            exc_info=True,
        )


def _emit_review_progress_from_update(
    review_id: str,
    progress_state: dict[str, Any],
    chunk: dict[str, Any],
) -> None:
    prepare_update = chunk.get("prepare_risk_reviews")
    if isinstance(prepare_update, dict) and "review_units" in prepare_update:
        total = len(prepare_update.get("review_units") or [])
        progress_state["total"] = total
        progress_state["processed"] = 0
        _persist_review_progress(
            review_id,
            {
                "progress": 0.0 if total else 1.0,
                "reviewed_clauses": 0,
                "total_clauses": total,
            },
        )

    worker_update = chunk.get("risk_review_worker")
    if not isinstance(worker_update, dict):
        return
    results = worker_update.get("risk_review_results") or []
    if not results:
        return

    processed = int(progress_state.get("processed") or 0) + len(results)
    progress_state["processed"] = processed
    total = int(progress_state.get("total") or processed)
    latest = results[-1] if isinstance(results[-1], dict) else {}
    review = latest.get("review") if isinstance(latest, dict) else {}
    if hasattr(review, "model_dump"):
        review = review.model_dump(mode="json")
    if not isinstance(review, dict):
        review = {}

    _persist_review_progress(
        review_id,
        {
            "progress": min(processed, total) / max(total, 1),
            "reviewed_clauses": processed,
            "total_clauses": total,
            "clause_id": review.get("clause_id"),
            "clause_no": review.get("clause_no"),
            "clause_title": review.get("title"),
            "risk_level": review.get("risk_level"),
            "finding_count": len(review.get("findings") or []),
        },
    )


def _persist_review_progress(review_id: str, payload: dict[str, Any]) -> None:
    try:
        with db_connection() as conn:
            storage.add_event(conn, review_id, "review_progress", payload)
    except Exception:
        logger.warning(
            "failed to persist review progress event: review_id=%s payload=%s",
            review_id,
            payload,
            exc_info=True,
        )


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


def _build_feedback_regeneration_prompt(
    *,
    suggestion: dict[str, Any],
    current_text: str,
    previous_new_text: str,
    comment: str,
) -> str:
    payload = suggestion.get("payload") or {}
    request = {
        "finding_id": suggestion.get("finding_id"),
        "risk_level": suggestion.get("risk_level"),
        "title": suggestion.get("title"),
        "guidance": suggestion.get("guidance"),
        "selected_text": suggestion.get("selected_text"),
        "source_citations": suggestion.get("source_citations") or [],
        "current_paragraph": current_text,
        "previous_suggested_paragraph": previous_new_text,
        "user_feedback": comment,
        "rationale": payload.get("rationale"),
        "issue_type": payload.get("issue_type"),
    }
    schema = {
        "title": "short Korean title",
        "guidance": "Korean explanation of how the new edit reflects the feedback",
        "selected_text": "exact risky substring from current_paragraph if applicable",
        "new_text": "full Korean replacement paragraph preserving numbering and scope",
    }
    return "\n\n".join(
        [
            "[task]",
            (
                "Revise the suggested contract edit using the user's feedback. "
                "Return a full replacement for current_paragraph in new_text. "
                "Preserve numbering, parties, amounts, dates, and unrelated wording unless feedback requires a change."
            ),
            "[request]",
            json.dumps(request, ensure_ascii=False),
            "[required_json_schema]",
            json.dumps(schema, ensure_ascii=False),
        ]
    )


def _parse_feedback_regeneration(answer: str) -> dict[str, Any]:
    cleaned = answer.strip()
    cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        cleaned = cleaned[start : end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise DocumentReviewServiceError(422, f"Feedback regeneration returned invalid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise DocumentReviewServiceError(422, "Feedback regeneration returned a non-object JSON payload.")
    return parsed


def _parser_paragraph_text(parser_result: dict[str, Any], target_id: str) -> str:
    for paragraph in parser_result.get("paragraphs") or []:
        if isinstance(paragraph, dict) and paragraph.get("node_id") == target_id:
            return str(paragraph.get("text_excerpt") or "")
    return ""


def _feedback_target_id(
    job: dict[str, Any],
    suggestion: dict[str, Any],
    proposed_edit: dict[str, Any],
) -> str:
    target_id = str(proposed_edit.get("target_id") or "")
    if target_id:
        return target_id

    finding_id = suggestion.get("finding_id")
    result = job.get("contract_review_result") or {}
    for finding in result.get("findings") or []:
        if not isinstance(finding, dict) or finding.get("finding_id") != finding_id:
            continue
        target_node_ids = finding.get("target_node_ids") or []
        if target_node_ids:
            return str(target_node_ids[0])
        annotation = finding.get("annotation") or {}
        if isinstance(annotation, dict) and annotation.get("target_id"):
            return str(annotation["target_id"])
    return ""


def _decision_payload(action: str, comment: str) -> dict[str, str]:
    return {
        "action": action,
        "comment": comment,
        "decided_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _generation_answer_text(result: Any) -> str:
    answer = getattr(result, "answer", None)
    return answer if isinstance(answer, str) else str(result)


def _text_diff(before: str, after: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="current",
            tofile="suggested",
            lineterm="",
        )
    )


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()
