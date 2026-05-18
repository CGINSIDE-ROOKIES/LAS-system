# Build context: apps/backend/ (one level up, needs api/, rag/, and doc_processor/)
# ── Stage 1: build ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy rag (local editable dependency) first
COPY rag/pyproject.toml rag/pyproject.toml
COPY rag/rag_pipeline/ rag/rag_pipeline/

# Copy doc_processor (local editable dependency)
COPY doc_processor/pyproject.toml doc_processor/README.md doc_processor/
COPY doc_processor/src/ doc_processor/src/

# Copy api project
COPY api/pyproject.toml api/uv.lock api/
COPY api/main.py api/main.py
COPY api/src/ api/src/
COPY api/alembic.ini api/alembic.ini
COPY api/alembic/ api/alembic/

WORKDIR /app/api
RUN uv sync --frozen --no-dev

# ── Stage 2: runtime ────────────────────────────────
FROM python:3.13-slim-bookworm

WORKDIR /app/api

COPY --from=builder /app/api/.venv /app/api/.venv
COPY --from=builder /app/api/main.py /app/api/main.py
COPY --from=builder /app/api/src/ /app/api/src/
COPY --from=builder /app/api/alembic.ini /app/api/alembic.ini
COPY --from=builder /app/api/alembic/ /app/api/alembic/
# Local packages are installed as editable — keep sources at expected paths
COPY --from=builder /app/rag/ /app/rag/
COPY --from=builder /app/doc_processor/ /app/doc_processor/

ENV PATH="/app/api/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
