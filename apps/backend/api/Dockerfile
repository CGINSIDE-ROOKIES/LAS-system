# Build context: apps/backend/ (one level up, needs both api/ and rag/)
# ── Stage 1: build ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy rag (local editable dependency) first
COPY rag/pyproject.toml rag/pyproject.toml
COPY rag/src/ rag/src/

# Copy api project
COPY api/pyproject.toml api/uv.lock api/
COPY api/main.py api/main.py
COPY api/src/ api/src/

WORKDIR /app/api
RUN uv sync --frozen --no-dev

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
