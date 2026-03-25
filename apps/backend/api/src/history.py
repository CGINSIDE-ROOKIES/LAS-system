"""Q&A 히스토리 DB 저장/조회."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg2.extensions


def save_qa(
    conn: psycopg2.extensions.connection,
    *,
    question: str,
    answer: str,
    law_context_status: str,
    retrieved_docs: list[dict[str, Any]],
    session_id: str | None = None,
) -> str:
    """qa_history + qa_sources 저장 후 qa_id(UUID) 반환."""
    with conn.cursor() as cur:
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
                INSERT INTO qa_sources (qa_id, source_id, doc_type, law_name, rank, score)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        qa_id,
                        doc.get("source_id"),
                        doc.get("doc_type"),
                        doc.get("law_name"),
                        doc.get("rank"),
                        doc.get("score"),
                    )
                    for doc in retrieved_docs
                ],
            )

    return str(qa_id)


def get_history(
    conn: psycopg2.extensions.connection,
    *,
    q: str | None = None,
    session_id: str | None = None,
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

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM qa_history h {where}",
            params,
        )
        total: int = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT h.id, h.session_id, h.question, h.answer,
                   h.law_context_status, h.created_at
            FROM qa_history h
            {where}
            ORDER BY h.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

        qa_ids = [str(row[0]) for row in rows]
        sources_by_qa: dict[str, list[dict[str, Any]]] = {qid: [] for qid in qa_ids}

        if qa_ids:
            cur.execute(
                """
                SELECT qa_id, source_id, doc_type, law_name, rank, score
                FROM qa_sources
                WHERE qa_id = ANY(%s::uuid[])
                ORDER BY qa_id, rank
                """,
                (qa_ids,),
            )
            for src in cur.fetchall():
                qa_id_str = str(src[0])
                if qa_id_str in sources_by_qa:
                    sources_by_qa[qa_id_str].append({
                        "source_id": src[1],
                        "doc_type": src[2],
                        "law_name": src[3],
                        "rank": src[4],
                        "score": src[5],
                    })

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
        for row in rows
    ]

    return {"items": items, "total": total}


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
            """
            SELECT source_id, doc_type, law_name, rank, score
            FROM qa_sources
            WHERE qa_id = %s
            ORDER BY rank
            """,
            (qa_id,),
        )
        sources = [
            {
                "source_id": src[0],
                "doc_type": src[1],
                "law_name": src[2],
                "rank": src[3],
                "score": src[4],
            }
            for src in cur.fetchall()
        ]

    return {
        "id": str(row[0]),
        "session_id": str(row[1]) if row[1] else None,
        "question": row[2],
        "answer": row[3],
        "law_context_status": row[4],
        "created_at": row[5].isoformat(),
        "sources": sources,
    }
