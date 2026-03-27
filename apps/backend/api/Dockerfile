# syntax=docker/dockerfile:1.7
#
# Build context: apps/backend/ (one level up, needs both api/ and rag/)
# ── Stage 1: build ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency metadata first so app source changes do not invalidate the
# heavy external dependency install layer.
COPY rag/pyproject.toml rag/pyproject.toml
COPY api/pyproject.toml api/uv.lock api/

WORKDIR /app/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-local

# Install the local editable dependency after the shared third-party packages
# have already been cached.
WORKDIR /app
COPY rag/rag_pipeline/ rag/rag_pipeline/

WORKDIR /app/api
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy the API source last so plain code changes reuse both dependency layers.
WORKDIR /app
COPY api/main.py api/main.py
COPY api/src/ api/src/

# ── Stage 2: runtime ────────────────────────────────
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY --from=builder /app/api/.venv /app/api/.venv
COPY --from=builder /app/api/main.py /app/main.py
COPY --from=builder /app/api/src/ /app/src/
# rag is installed as editable — keep source at expected path
COPY --from=builder /app/rag/ /app/rag/

ENV PATH="/app/api/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
