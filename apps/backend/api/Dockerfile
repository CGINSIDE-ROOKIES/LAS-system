# Build context: apps/backend/ (one level up, needs both api/ and rag/)
# ── Stage 1: build ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /build

# Copy rag (local editable dependency) first
COPY rag/pyproject.toml rag/pyproject.toml
COPY rag/src/ rag/src/

# Copy api project
COPY api/pyproject.toml api/pyproject.toml
COPY api/main.py api/main.py
COPY api/src/ api/src/

WORKDIR /build/api
RUN uv sync --no-dev

# ── Stage 2: runtime ────────────────────────────────
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY --from=builder /build/api/.venv /app/.venv
COPY --from=builder /build/api/main.py /app/main.py
COPY --from=builder /build/api/src/ /app/src/
# rag is installed as editable — keep source at expected path
COPY --from=builder /build/rag/ /build/rag/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
