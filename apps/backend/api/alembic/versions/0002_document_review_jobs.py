"""document review job orchestration tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_review_jobs (
            id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            status                     TEXT NOT NULL DEFAULT 'queued',
            stage                      TEXT NOT NULL DEFAULT 'upload_saved',
            progress                   DOUBLE PRECISION NOT NULL DEFAULT 0,
            source_name                TEXT NOT NULL,
            source_doc_type            TEXT,
            original_artifact_path     TEXT NOT NULL,
            edited_artifact_path       TEXT,
            parser_result              JSONB,
            contract_review_result     JSONB,
            options                    JSONB NOT NULL DEFAULT '{}'::jsonb,
            current_preview_kind       TEXT,
            error                      TEXT,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at               TIMESTAMPTZ,
            CONSTRAINT document_review_jobs_status_check
                CHECK (status IN ('queued', 'running', 'hitl_waiting', 'applying', 'completed', 'failed')),
            CONSTRAINT document_review_jobs_stage_check
                CHECK (stage IN (
                    'upload_saved',
                    'parser_started',
                    'parser_completed',
                    'review_started',
                    'review_progress',
                    'hitl_waiting',
                    'apply_started',
                    'apply_completed',
                    'completed',
                    'failed'
                )),
            CONSTRAINT document_review_jobs_preview_kind_check
                CHECK (current_preview_kind IS NULL OR current_preview_kind IN ('parser', 'risk', 'edited'))
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS document_review_events (
            review_id      UUID NOT NULL REFERENCES document_review_jobs(id) ON DELETE CASCADE,
            seq            INT NOT NULL,
            stage          TEXT NOT NULL,
            payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
            timestamp      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (review_id, seq)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS document_review_suggestions (
            review_id      UUID NOT NULL REFERENCES document_review_jobs(id) ON DELETE CASCADE,
            finding_id     TEXT NOT NULL,
            request_id     TEXT,
            clause_id      TEXT,
            risk_level     TEXT,
            status         TEXT NOT NULL DEFAULT 'pending',
            payload        JSONB NOT NULL DEFAULT '{}'::jsonb,
            proposed_edit  JSONB,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (review_id, finding_id),
            CONSTRAINT document_review_suggestions_status_check
                CHECK (status IN ('pending', 'accepted', 'rejected', 'feedback'))
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS document_review_artifacts (
            review_id      UUID NOT NULL REFERENCES document_review_jobs(id) ON DELETE CASCADE,
            kind           TEXT NOT NULL,
            path           TEXT NOT NULL,
            content_type   TEXT NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (review_id, kind),
            CONSTRAINT document_review_artifacts_kind_check
                CHECK (kind IN ('original', 'parser_preview', 'risk_preview', 'edited', 'edited_preview'))
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_document_review_jobs_updated_at ON document_review_jobs (updated_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_document_review_events_review_seq ON document_review_events (review_id, seq)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_document_review_suggestions_review_id ON document_review_suggestions (review_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_document_review_artifacts_review_id ON document_review_artifacts (review_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_review_artifacts")
    op.execute("DROP TABLE IF EXISTS document_review_suggestions")
    op.execute("DROP TABLE IF EXISTS document_review_events")
    op.execute("DROP TABLE IF EXISTS document_review_jobs")
