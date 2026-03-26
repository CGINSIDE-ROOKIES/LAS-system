CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS qa_history (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID,
    question            TEXT NOT NULL,
    answer              TEXT,
    law_context_status  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS qa_sources (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    qa_id       UUID NOT NULL REFERENCES qa_history(id) ON DELETE CASCADE,
    source_id   TEXT NOT NULL,
    doc_type    TEXT,
    law_name    TEXT,
    rank        INT,
    score       FLOAT
);

CREATE TABLE IF NOT EXISTS feedback (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    qa_id       UUID NOT NULL REFERENCES qa_history(id) ON DELETE CASCADE,
    rating      INT CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qa_history_created_at ON qa_history (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qa_history_session_id ON qa_history (session_id);
CREATE INDEX IF NOT EXISTS idx_qa_sources_qa_id ON qa_sources (qa_id);
CREATE INDEX IF NOT EXISTS idx_feedback_qa_id ON feedback (qa_id);
