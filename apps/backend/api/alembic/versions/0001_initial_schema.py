"""initial schema (001~005 SQL 통합)

Revision ID: 0001
Revises:
Create Date: 2026-04-01
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.execute("""
        CREATE TABLE IF NOT EXISTS qa_history (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id         UUID,
            question           TEXT NOT NULL,
            answer             TEXT,
            law_context_status TEXT,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS qa_sources (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            qa_id      UUID NOT NULL REFERENCES qa_history(id) ON DELETE CASCADE,
            source_id  TEXT NOT NULL,
            doc_type   TEXT,
            law_name   TEXT,
            article_no TEXT,
            rank       INT,
            score      FLOAT,
            snippet    TEXT,
            text       TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            qa_id      UUID NOT NULL REFERENCES qa_history(id) ON DELETE CASCADE,
            thumbs_up  BOOLEAN NOT NULL DEFAULT false,
            comment    TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT feedback_qa_id_unique UNIQUE (qa_id)
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_qa_history_created_at ON qa_history (created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_qa_history_session_id ON qa_history (session_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_qa_sources_qa_id ON qa_sources (qa_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_feedback_qa_id ON feedback (qa_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback")
    op.execute("DROP TABLE IF EXISTS qa_sources")
    op.execute("DROP TABLE IF EXISTS qa_history")
