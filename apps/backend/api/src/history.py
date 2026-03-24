"""Q&A 히스토리 DB 저장/조회."""

from __future__ import annotations

from typing import Any

import psycopg2.extensions


def save_qa(
    conn: psycopg2.extensions.connection,
    *,
    question: str,
    answer: str,
    law_context_status: str,
    retrieved_docs: list[dict[str, Any]],
) -> str:
    """qa_history + qa_sources 저장 후 qa_id(UUID) 반환."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO qa_history (question, answer, law_context_status)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (question, answer, law_context_status),
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
