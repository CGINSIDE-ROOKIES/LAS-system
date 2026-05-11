from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2.extensions
from psycopg2.extras import Json, RealDictCursor

from doc_processor.contract_review import ContractReviewFinding, ContractReviewResult

from .previews import finding_source_citations

_CONTENT_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".hwp": "application/octet-stream",
    ".hwpx": "application/octet-stream",
    ".pdf": "application/pdf",
    ".html": "text/html; charset=utf-8",
}


def storage_root() -> Path:
    default_root = Path(__file__).resolve().parents[2] / "storage" / "document_reviews"
    return Path(os.getenv("DOCUMENT_REVIEW_STORAGE_DIR", str(default_root))).expanduser()


def review_dir(review_id: str) -> Path:
    path = storage_root() / review_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def source_doc_type_from_name(filename: str) -> str | None:
    suffix = Path(filename).suffix.lower().lstrip(".")
    return suffix or None


def content_type_for_path(path: str | Path) -> str:
    return _CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def original_path_for(review_id: str, source_name: str) -> Path:
    suffix = Path(source_name).suffix.lower() or ".bin"
    return review_dir(review_id) / f"original{suffix}"


def parser_preview_path_for(review_id: str) -> Path:
    return review_dir(review_id) / "parser_preview.html"


def risk_preview_path_for(review_id: str) -> Path:
    return review_dir(review_id) / "risk_preview.html"


def edited_path_for(review_id: str, source_name: str) -> Path:
    suffix = Path(source_name).suffix.lower() or ".docx"
    if suffix == ".hwp":
        suffix = ".hwpx"
    return review_dir(review_id) / f"edited{suffix}"


def edited_preview_path_for(review_id: str) -> Path:
    return review_dir(review_id) / "edited_preview.html"


def create_job(
    conn: psycopg2.extensions.connection,
    *,
    review_id: str,
    source_name: str,
    source_doc_type: str | None,
    original_artifact_path: str,
    options: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_review_jobs (
                id, status, stage, progress, source_name, source_doc_type,
                original_artifact_path, options
            )
            VALUES (%s, 'queued', 'upload_saved', 0.05, %s, %s, %s, %s)
            """,
            (review_id, source_name, source_doc_type, original_artifact_path, Json(options)),
        )


def get_job(conn: psycopg2.extensions.connection, review_id: str) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM document_review_jobs WHERE id = %s", (review_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def update_job(conn: psycopg2.extensions.connection, review_id: str, **fields: Any) -> None:
    if not fields:
        return
    assignments: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key in {"parser_result", "contract_review_result", "options"}:
            params.append(Json(value) if value is not None else None)
        else:
            params.append(value)
        assignments.append(f"{key} = %s")
    assignments.append("updated_at = now()")
    if fields.get("status") in {"completed", "failed"}:
        assignments.append("completed_at = COALESCE(completed_at, now())")
    params.append(review_id)
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE document_review_jobs SET {', '.join(assignments)} WHERE id = %s",
            params,
        )


def add_event(
    conn: psycopg2.extensions.connection,
    review_id: str,
    stage: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_payload = payload or {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (review_id,))
        cur.execute(
            """
            INSERT INTO document_review_events (review_id, seq, stage, payload)
            SELECT %s, COALESCE(MAX(seq), 0) + 1, %s, %s
            FROM document_review_events
            WHERE review_id = %s
            RETURNING review_id, seq, stage, payload, timestamp
            """,
            (review_id, stage, Json(event_payload), review_id),
        )
        row = cur.fetchone()
    return _event_to_dict(dict(row))


def list_events(
    conn: psycopg2.extensions.connection,
    review_id: str,
    *,
    after_seq: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT review_id, seq, stage, payload, timestamp
            FROM document_review_events
            WHERE review_id = %s AND seq > %s
            ORDER BY seq
            LIMIT %s
            """,
            (review_id, after_seq, limit),
        )
        rows = cur.fetchall()
    return [_event_to_dict(dict(row)) for row in rows]


def upsert_artifact(
    conn: psycopg2.extensions.connection,
    *,
    review_id: str,
    kind: str,
    path: str,
    content_type: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_review_artifacts (review_id, kind, path, content_type)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (review_id, kind) DO UPDATE
                SET path = EXCLUDED.path,
                    content_type = EXCLUDED.content_type,
                    created_at = now()
            """,
            (review_id, kind, path, content_type),
        )


def get_artifact(conn: psycopg2.extensions.connection, review_id: str, kind: str) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT review_id, kind, path, content_type, created_at
            FROM document_review_artifacts
            WHERE review_id = %s AND kind = %s
            """,
            (review_id, kind),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def artifact_flags(conn: psycopg2.extensions.connection, review_id: str) -> dict[str, bool]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT kind FROM document_review_artifacts WHERE review_id = %s",
            (review_id,),
        )
        kinds = {row[0] for row in cur.fetchall()}
    return {
        "original": "original" in kinds,
        "parser_preview": "parser_preview" in kinds,
        "risk_preview": "risk_preview" in kinds,
        "edited": "edited" in kinds,
        "edited_preview": "edited_preview" in kinds,
    }


def preview_artifact_kind(job: dict[str, Any], requested_kind: str) -> str:
    if requested_kind == "parser":
        return "parser_preview"
    if requested_kind == "risk":
        return "risk_preview"
    if requested_kind == "edited":
        return "edited_preview"
    current = job.get("current_preview_kind")
    if current == "edited":
        return "edited_preview"
    if current == "risk":
        return "risk_preview"
    return "parser_preview"


def save_suggestions_from_result(
    conn: psycopg2.extensions.connection,
    review_id: str,
    result: ContractReviewResult,
) -> None:
    with conn.cursor() as cur:
        for finding in result.findings:
            payload = _suggestion_payload(finding)
            proposed_edit = (
                finding.proposed_edit.model_dump(mode="json")
                if finding.proposed_edit is not None
                else None
            )
            request_id = payload.get("request_id")
            cur.execute(
                """
                INSERT INTO document_review_suggestions (
                    review_id, finding_id, request_id, clause_id, risk_level,
                    status, payload, proposed_edit
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (review_id, finding_id) DO UPDATE
                    SET request_id = EXCLUDED.request_id,
                        clause_id = EXCLUDED.clause_id,
                        risk_level = EXCLUDED.risk_level,
                        status = EXCLUDED.status,
                        payload = CASE
                            WHEN document_review_suggestions.payload ? 'decision'
                            THEN EXCLUDED.payload || jsonb_build_object(
                                'decision',
                                document_review_suggestions.payload->'decision'
                            )
                            ELSE EXCLUDED.payload
                        END,
                        proposed_edit = EXCLUDED.proposed_edit,
                        updated_at = now()
                """,
                (
                    review_id,
                    finding.finding_id,
                    request_id,
                    finding.clause_id,
                    finding.risk_level,
                    finding.status,
                    Json(payload),
                    Json(proposed_edit) if proposed_edit is not None else None,
                ),
            )


def list_suggestions(conn: psycopg2.extensions.connection, review_id: str) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT finding_id, request_id, clause_id, risk_level, status, payload, proposed_edit
            FROM document_review_suggestions
            WHERE review_id = %s
            ORDER BY
                CASE risk_level
                    WHEN 'crit' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'mid' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                finding_id
            """,
            (review_id,),
        )
        rows = cur.fetchall()
    return [_suggestion_row_to_dict(dict(row)) for row in rows]


def get_suggestion(conn: psycopg2.extensions.connection, review_id: str, finding_id: str) -> dict[str, Any] | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT finding_id, request_id, clause_id, risk_level, status, payload, proposed_edit
            FROM document_review_suggestions
            WHERE review_id = %s AND finding_id = %s
            """,
            (review_id, finding_id),
        )
        row = cur.fetchone()
    return _suggestion_row_to_dict(dict(row)) if row else None


def update_suggestion_decision(
    conn: psycopg2.extensions.connection,
    *,
    review_id: str,
    finding_id: str,
    action: str,
    comment: str | None,
) -> dict[str, Any] | None:
    status = _status_from_action(action)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT payload
            FROM document_review_suggestions
            WHERE review_id = %s AND finding_id = %s
            FOR UPDATE
            """,
            (review_id, finding_id),
        )
        row = cur.fetchone()
        if row is None:
            return None
        payload = dict(row["payload"] or {})
        payload["decision"] = {
            "action": action,
            "comment": comment or "",
            "decided_at": datetime.utcnow().isoformat() + "Z",
        }
        cur.execute(
            """
            UPDATE document_review_suggestions
            SET status = %s,
                payload = %s,
                updated_at = now()
            WHERE review_id = %s AND finding_id = %s
            RETURNING finding_id, request_id, clause_id, risk_level, status, payload, proposed_edit
            """,
            (status, Json(payload), review_id, finding_id),
        )
        updated = cur.fetchone()
    return _suggestion_row_to_dict(dict(updated)) if updated else None


def resume_decisions(conn: psycopg2.extensions.connection, review_id: str) -> list[dict[str, Any]]:
    rows = list_suggestions(conn, review_id)
    decisions: list[dict[str, Any]] = []
    for row in rows:
        status = row["status"]
        if status == "pending":
            continue
        decision_payload = (row.get("payload") or {}).get("decision") or {}
        decisions.append(
            {
                "finding_id": row["finding_id"],
                "action": _action_from_status(status),
                "comment": decision_payload.get("comment", ""),
            }
        )
    return decisions


def accepted_suggestions(conn: psycopg2.extensions.connection, review_id: str) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT finding_id, risk_level, proposed_edit
            FROM document_review_suggestions
            WHERE review_id = %s
              AND status = 'accepted'
              AND proposed_edit IS NOT NULL
            ORDER BY
                CASE risk_level
                    WHEN 'crit' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'mid' THEN 3
                    WHEN 'low' THEN 4
                    ELSE 5
                END,
                finding_id
            """,
            (review_id,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def summarize_job(conn: psycopg2.extensions.connection, review_id: str) -> dict[str, Any] | None:
    job = get_job(conn, review_id)
    if job is None:
        return None
    flags = artifact_flags(conn, review_id)
    result = job.get("contract_review_result") or {}
    risk_counts = result.get("clause_risk_counts") or {}
    completed_at = job.get("completed_at")
    return {
        "review_id": str(job["id"]),
        "status": job["status"],
        "stage": job["stage"],
        "progress": float(job.get("progress") or 0),
        "source_name": job["source_name"],
        "source_doc_type": job.get("source_doc_type"),
        "current_preview_kind": job.get("current_preview_kind"),
        "risk_counts": risk_counts,
        "artifact_flags": flags,
        "error": job.get("error"),
        "created_at": job["created_at"].isoformat(),
        "updated_at": job["updated_at"].isoformat(),
        "completed_at": completed_at.isoformat() if completed_at else None,
    }


def _suggestion_payload(finding: ContractReviewFinding) -> dict[str, Any]:
    if finding.human_request is not None:
        payload = finding.human_request.model_dump(mode="json")
    else:
        payload = {
            "finding_id": finding.finding_id,
            "clause_id": finding.clause_id,
            "clause_no": finding.clause_no,
            "risk_level": finding.risk_level,
            "title": finding.title,
            "kind": "finding",
            "prompt": finding.human_question,
            "guidance": finding.recommendation,
            "selected_text": finding.problematic_text,
            "source_citations": finding_source_citations(finding),
            "allowed_actions": ["reject", "feedback"],
        }
    payload["rationale"] = finding.rationale
    payload["recommendation"] = finding.recommendation
    payload["issue_type"] = finding.issue_type
    return payload


def _suggestion_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or {}
    return {
        "finding_id": row["finding_id"],
        "request_id": row.get("request_id") or payload.get("request_id"),
        "clause_id": row.get("clause_id") or payload.get("clause_id"),
        "risk_level": row.get("risk_level") or payload.get("risk_level"),
        "status": row["status"],
        "title": payload.get("title", ""),
        "kind": payload.get("kind", "finding"),
        "prompt": payload.get("prompt", ""),
        "guidance": payload.get("guidance", ""),
        "selected_text": payload.get("selected_text", ""),
        "diff": payload.get("diff"),
        "source_citations": payload.get("source_citations") or [],
        "proposed_edit": row.get("proposed_edit"),
        "allowed_actions": payload.get("allowed_actions") or [],
        "payload": payload,
    }


def _event_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = row.get("timestamp")
    return {
        "review_id": str(row["review_id"]),
        "seq": row["seq"],
        "stage": row["stage"],
        "payload": row.get("payload") or {},
        "timestamp": timestamp.isoformat() if timestamp else None,
    }


def _status_from_action(action: str) -> str:
    if action == "accept":
        return "accepted"
    if action == "reject":
        return "rejected"
    return "feedback"


def _action_from_status(status: str) -> str:
    if status == "accepted":
        return "accept"
    if status == "rejected":
        return "reject"
    return "feedback"
