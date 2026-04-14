"""Q&A 히스토리 DB 저장/조회."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import psycopg2.extensions

_SOURCE_COLUMNS_SQL = "source_id, doc_type, law_name, article_no, rank, score, snippet, text"


def _source_row_to_dict(src: tuple[Any, ...]) -> dict[str, Any]:
    """qa_sources SELECT row를 API 응답 dict로 변환한다."""
    return {
        "source_id": src[0],
        "doc_type": src[1],
        "law_name": src[2],
        "article_no": src[3],
        "rank": src[4],
        "score": src[5],
        "snippet": src[6],
        "text": src[7],
    }


def _parse_iso_datetime(value: str, *, field_name: str, is_end_bound: bool) -> datetime:
    """ISO 문자열을 datetime으로 변환한다.

    - YYYY-MM-DD 입력:
      - date_from: 해당 일 00:00:00
      - date_to  : 다음 날 00:00:00 (exclusive upper bound)
    - datetime 입력: 그대로 사용
    """
    raw = value.strip()
    if not raw:
        raise ValueError(f"{field_name} 값이 비어 있습니다.")
    try:
        if "T" in raw:
            dt = datetime.fromisoformat(raw)
            return dt
        d = date.fromisoformat(raw)
        if is_end_bound:
            return datetime.combine(d + timedelta(days=1), datetime.min.time())
        return datetime.combine(d, datetime.min.time())
    except ValueError as exc:
        raise ValueError(f"{field_name}는 ISO 형식이어야 합니다. 예: 2026-01-01") from exc


def save_qa(
    conn: psycopg2.extensions.connection,
    *,
    question: str,
    answer: str,
    law_context_status: str,
    retrieved_docs: list[dict[str, Any]],
    session_id: str | None = None,
) -> str:
    """qa_history + qa_sources 저장 후 qa_id(UUID) 반환.

    savepoint를 사용해 내부 INSERT 중 일부가 실패해도 부분 저장이 남지 않게 한다.
    """
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT save_qa_sp")
        try:
            cur.execute(
                """
                INSERT INTO qa_history (session_id, question, answer, law_context_status)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (session_id or None, question, answer, law_context_status),
            )
            qa_id: str = cur.fetchone()[0]

            if retrieved_docs:
                cur.executemany(
                    """
                    INSERT INTO qa_sources (qa_id, source_id, doc_type, law_name, article_no, rank, score, snippet, text)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            qa_id,
                            doc.get("source_id"),
                            doc.get("doc_type"),
                            doc.get("law_name"),
                            doc.get("article_no") or None,
                            doc.get("rank"),
                            doc.get("score"),
                            doc.get("snippet") or None,
                            doc.get("text") or None,
                        )
                        for doc in retrieved_docs
                    ],
                )
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT save_qa_sp")
            cur.execute("RELEASE SAVEPOINT save_qa_sp")
            raise
        cur.execute("RELEASE SAVEPOINT save_qa_sp")

    return str(qa_id)


def get_history(
    conn: psycopg2.extensions.connection,
    *,
    q: str | None = None,
    session_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """qa_history 목록과 각 항목의 sources를 반환한다."""
    conditions: list[str] = []
    params: list[Any] = []

    if q:
        conditions.append("(h.question ILIKE %s OR h.answer ILIKE %s)")
        params.extend([f"%{q}%", f"%{q}%"])
    if session_id:
        conditions.append("h.session_id = %s")
        params.append(session_id)
    if date_from:
        dt_from = _parse_iso_datetime(date_from, field_name="date_from", is_end_bound=False)
        conditions.append("h.created_at >= %s")
        params.append(dt_from)
    if date_to:
        dt_to = _parse_iso_datetime(date_to, field_name="date_to", is_end_bound=True)
        conditions.append("h.created_at < %s")
        params.append(dt_to)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH filtered AS (
                SELECT h.id, h.session_id, h.question, h.answer, h.law_context_status, h.created_at
                FROM qa_history h
                {where}
            ),
            total AS (
                SELECT COUNT(*)::int AS total_count FROM filtered
            )
            SELECT p.id, p.session_id, p.question, p.answer, p.law_context_status, p.created_at,
                   t.total_count
            FROM total t
            LEFT JOIN LATERAL (
                SELECT *
                FROM filtered
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            ) p ON TRUE
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

        total: int = int(rows[0][6]) if rows else 0
        paged_rows = [row for row in rows if row[0] is not None]
        qa_ids = [str(row[0]) for row in paged_rows]
        sources_by_qa: dict[str, list[dict[str, Any]]] = {qid: [] for qid in qa_ids}

        if qa_ids:
            cur.execute(
                """
                SELECT qa_id, source_id, doc_type, law_name, article_no, rank, score, snippet, text
                FROM qa_sources
                WHERE qa_id = ANY(%s::uuid[])
                ORDER BY qa_id, rank
                """,
                (qa_ids,),
            )
            for src in cur.fetchall():
                qa_id_str = str(src[0])
                if qa_id_str in sources_by_qa:
                    sources_by_qa[qa_id_str].append(_source_row_to_dict(src[1:]))
    

    items = [
        {
            "id": str(row[0]),
            "session_id": str(row[1]) if row[1] else None,
            "question": row[2],
            "answer": row[3],
            "law_context_status": row[4],
            "created_at": row[5].isoformat(),
            "sources": sources_by_qa[str(row[0])],
        }
        for row in paged_rows
    ]

    return {"items": items, "total": total}


def delete_history_item(
    conn: psycopg2.extensions.connection,
    qa_id: str,
) -> bool:
    """단건 Q&A 히스토리를 삭제한다. 삭제 성공 시 True, 존재하지 않으면 False."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM qa_history WHERE id = %s",
            (qa_id,),
        )
        return cur.rowcount > 0


def delete_history_items(
    conn: psycopg2.extensions.connection,
    qa_ids: list[str],
) -> int:
    """여러 Q&A 히스토리를 한 번에 삭제한다. 실제 삭제된 건수를 반환한다."""
    if not qa_ids:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM qa_history WHERE id = ANY(%s::uuid[])",
            (qa_ids,),
        )
        return cur.rowcount


def save_feedback(
    conn: psycopg2.extensions.connection,
    *,
    qa_id: str,
    thumbs_up: bool,
    comment: str | None = None,
) -> str:
    """feedback 저장 후 feedback id(UUID) 반환. qa_id가 없으면 ValueError."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO feedback (qa_id, thumbs_up, comment)
            SELECT h.id, %s, %s
            FROM qa_history h
            WHERE h.id = %s
            ON CONFLICT (qa_id) DO UPDATE
                SET thumbs_up = EXCLUDED.thumbs_up,
                    comment   = EXCLUDED.comment,
                    created_at = now()
            RETURNING id
            """,
            (thumbs_up, comment, qa_id),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"qa_id {qa_id} not found")
        return str(row[0])


def get_history_item(
    conn: psycopg2.extensions.connection,
    qa_id: str,
) -> dict[str, Any] | None:
    """단건 Q&A 히스토리와 sources를 반환한다. 없으면 None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, question, answer, law_context_status, created_at
            FROM qa_history
            WHERE id = %s
            """,
            (qa_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None

        cur.execute(
            f"""
            SELECT {_SOURCE_COLUMNS_SQL}
            FROM qa_sources
            WHERE qa_id = %s
            ORDER BY rank
            """,
            (qa_id,),
        )
        sources = [_source_row_to_dict(src) for src in cur.fetchall()]

    return {
        "id": str(row[0]),
        "session_id": str(row[1]) if row[1] else None,
        "question": row[2],
        "answer": row[3],
        "law_context_status": row[4],
        "created_at": row[5].isoformat(),
        "sources": sources,
    }
