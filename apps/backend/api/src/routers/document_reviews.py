from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from uuid import uuid4

import psycopg2.extensions
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import ValidationError

from src.db import db_connection, get_db
from src.document_reviews import storage
from src.document_reviews.models import (
    ApplyDocumentReviewResponse,
    CreateDocumentReviewResponse,
    DocumentReviewOptions,
    DocumentReviewSuggestion,
    DocumentReviewSuggestionsResponse,
    DocumentReviewSummary,
    PreviewKind,
    ResumeDocumentReviewResponse,
    SuggestionDecisionRequest,
)
from src.document_reviews.service import (
    DocumentReviewServiceError,
    apply_document_review,
    regenerate_feedback_suggestion,
    resume_document_review,
    run_document_review_job,
)

router = APIRouter(tags=["document-reviews"])
logger = logging.getLogger(__name__)


@router.post("", response_model=CreateDocumentReviewResponse, status_code=202)
async def create_document_review(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    options: str | None = Form(default=None),
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> CreateDocumentReviewResponse:
    try:
        parsed_options = DocumentReviewOptions.from_multipart_options(options)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    source_name = Path(file.filename or "document").name
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    review_id = str(uuid4())
    original_path = storage.original_path_for(review_id, source_name)
    original_path.write_bytes(content)
    source_doc_type = storage.source_doc_type_from_name(source_name)
    logger.info(
        "document review create accepted: review_id=%s source_name=%s source_doc_type=%s bytes=%s content_type=%s storage_path=%s",
        review_id,
        source_name,
        source_doc_type,
        len(content),
        file.content_type,
        original_path,
    )

    storage.create_job(
        conn,
        review_id=review_id,
        source_name=source_name,
        source_doc_type=source_doc_type,
        original_artifact_path=str(original_path),
        options=parsed_options.model_dump(mode="json"),
    )
    storage.upsert_artifact(
        conn,
        review_id=review_id,
        kind="original",
        path=str(original_path),
        content_type=file.content_type or storage.content_type_for_path(original_path),
    )
    storage.add_event(
        conn,
        review_id,
        "upload_saved",
        {
            "source_name": source_name,
            "source_doc_type": source_doc_type,
            "events_url": _events_url(review_id),
        },
    )
    storage.add_event(
        conn,
        review_id,
        "parser_progress",
        {"phase": "upload_saved", "progress": 0.02},
    )
    conn.commit()

    background_tasks.add_task(run_document_review_job, review_id, parsed_options.model_dump(mode="json"))
    logger.info("document review background task queued: review_id=%s", review_id)
    return CreateDocumentReviewResponse(
        review_id=review_id,
        status="queued",
        events_url=_events_url(review_id),
    )


@router.get("/{review_id}", response_model=DocumentReviewSummary)
def get_document_review(
    review_id: str,
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> DocumentReviewSummary:
    summary = storage.summarize_job(conn, review_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="Document review not found.")
    flags = summary["artifact_flags"]
    summary["preview_url"] = _preview_url(review_id)
    summary["events_url"] = _events_url(review_id)
    summary["suggestions_url"] = _suggestions_url(review_id)
    summary["download_url"] = _download_url(review_id) if flags.get("edited") else None
    return DocumentReviewSummary.model_validate(summary)


@router.get("/{review_id}/events")
def stream_document_review_events(
    review_id: str,
    after_seq: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    initial_after_seq = max(after_seq, _last_event_seq(last_event_id))
    with db_connection() as conn:
        if storage.get_job(conn, review_id) is None:
            raise HTTPException(status_code=404, detail="Document review not found.")
    logger.info(
        "document review event stream opened: review_id=%s after_seq=%s last_event_id=%s cursor=%s",
        review_id,
        after_seq,
        last_event_id,
        initial_after_seq,
    )

    def generate():
        cursor = initial_after_seq
        last_keepalive = time.monotonic()
        yield "retry: 3000\n\n"
        while True:
            with db_connection() as conn:
                events = storage.list_events(conn, review_id, after_seq=cursor)
                job = storage.get_job(conn, review_id)
            for event in events:
                cursor = int(event["seq"])
                yield _sse_event(event)
            if job and job["status"] in {"completed", "failed"} and not events:
                logger.info(
                    "document review event stream closed: review_id=%s cursor=%s status=%s stage=%s",
                    review_id,
                    cursor,
                    job["status"],
                    job["stage"],
                )
                break
            if not events and time.monotonic() - last_keepalive >= 15:
                last_keepalive = time.monotonic()
                yield ": keepalive\n\n"
            if not events:
                time.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.get("/{review_id}/preview.html", response_class=HTMLResponse)
def get_document_review_preview(
    review_id: str,
    kind: PreviewKind = Query(default="latest"),
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> HTMLResponse:
    job = storage.get_job(conn, review_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Document review not found.")
    artifact_kind = storage.preview_artifact_kind(job, kind)
    artifact = storage.get_artifact(conn, review_id, artifact_kind)
    if artifact is None:
        logger.info(
            "document review preview not ready: review_id=%s requested_kind=%s resolved_kind=%s status=%s stage=%s current_preview_kind=%s artifact_flags=%s",
            review_id,
            kind,
            artifact_kind,
            job["status"],
            job["stage"],
            job.get("current_preview_kind"),
            storage.artifact_flags(conn, review_id),
        )
        raise HTTPException(status_code=404, detail="Preview is not available yet.")
    path = Path(artifact["path"])
    if not path.exists():
        logger.warning(
            "document review preview artifact missing on disk: review_id=%s requested_kind=%s resolved_kind=%s path=%s storage_root=%s",
            review_id,
            kind,
            artifact_kind,
            path,
            storage.storage_root(),
        )
        raise HTTPException(status_code=404, detail="Preview artifact is missing.")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@router.get("/{review_id}/suggestions", response_model=DocumentReviewSuggestionsResponse)
def get_document_review_suggestions(
    review_id: str,
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> DocumentReviewSuggestionsResponse:
    if storage.get_job(conn, review_id) is None:
        raise HTTPException(status_code=404, detail="Document review not found.")
    items = [
        DocumentReviewSuggestion.model_validate(row)
        for row in storage.list_suggestions(conn, review_id)
    ]
    return DocumentReviewSuggestionsResponse(items=items, total=len(items))


@router.post("/{review_id}/suggestions/{finding_id}/decision", response_model=DocumentReviewSuggestion)
def decide_document_review_suggestion(
    review_id: str,
    finding_id: str,
    request: SuggestionDecisionRequest,
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> DocumentReviewSuggestion:
    if storage.get_job(conn, review_id) is None:
        raise HTTPException(status_code=404, detail="Document review not found.")
    try:
        if request.action == "feedback":
            if not (request.comment or "").strip():
                raise HTTPException(status_code=400, detail="Feedback comment is required.")
            suggestion = regenerate_feedback_suggestion(
                conn,
                review_id=review_id,
                finding_id=finding_id,
                comment=request.comment.strip(),
            )
        else:
            suggestion = storage.update_suggestion_decision(
                conn,
                review_id=review_id,
                finding_id=finding_id,
                action=request.action,
                comment=request.comment,
            )
    except DocumentReviewServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    logger.info(
        "document review suggestion decision saved: review_id=%s finding_id=%s action=%s comment_chars=%s",
        review_id,
        finding_id,
        request.action,
        len(request.comment or ""),
    )
    storage.add_event(
        conn,
        review_id,
        "hitl_waiting",
        {
            "finding_id": finding_id,
            "action": request.action,
            "suggestions_url": _suggestions_url(review_id),
        },
    )
    return DocumentReviewSuggestion.model_validate(suggestion)


@router.post("/{review_id}/resume", response_model=ResumeDocumentReviewResponse)
def resume_review(
    review_id: str,
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> ResumeDocumentReviewResponse:
    try:
        return resume_document_review(conn, review_id)
    except DocumentReviewServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/{review_id}/apply", response_model=ApplyDocumentReviewResponse)
def apply_review(
    review_id: str,
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> ApplyDocumentReviewResponse:
    try:
        return apply_document_review(conn, review_id)
    except DocumentReviewServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/{review_id}/download")
def download_reviewed_document(
    review_id: str,
    conn: psycopg2.extensions.connection = Depends(get_db),
) -> FileResponse:
    job = storage.get_job(conn, review_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Document review not found.")
    artifact = storage.get_artifact(conn, review_id, "edited")
    if artifact is None:
        raise HTTPException(status_code=404, detail="Edited document is not available.")
    path = Path(artifact["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Edited document artifact is missing.")
    filename = f"reviewed_{Path(job['source_name']).stem}{path.suffix}"
    return FileResponse(
        path,
        media_type=artifact["content_type"],
        filename=filename,
    )


def _sse_event(event: dict) -> str:
    payload = {
        "type": event["stage"],
        "seq": event["seq"],
        "timestamp": event.get("timestamp"),
        **(event.get("payload") or {}),
    }
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {event['seq']}\nevent: {event['stage']}\ndata: {data}\n\n"


def _last_event_seq(last_event_id: str | None) -> int:
    if not last_event_id:
        return 0
    try:
        return max(0, int(last_event_id))
    except ValueError:
        return 0


def _events_url(review_id: str) -> str:
    return f"/api/v1/document-reviews/{review_id}/events"


def _preview_url(review_id: str) -> str:
    return f"/api/v1/document-reviews/{review_id}/preview.html?kind=latest"


def _suggestions_url(review_id: str) -> str:
    return f"/api/v1/document-reviews/{review_id}/suggestions"


def _download_url(review_id: str) -> str:
    return f"/api/v1/document-reviews/{review_id}/download"
