# Build context: apps/backend/law-updater/

# ── Stage 1: build ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY config/ /app/config/
COPY scripts/ /app/scripts/
COPY src/ /app/src/

# ── Stage 2: runtime ────────────────────────────────
FROM python:3.12-slim-bookworm

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/config/ /app/config/
COPY --from=builder /app/scripts/ /app/scripts/
COPY --from=builder /app/src/ /app/src/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
