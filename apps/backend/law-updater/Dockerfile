# Build context: apps/backend/law-updater/

# ── Stage 1: build ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app/law-updater

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY config/ /app/law-updater/config/
COPY scripts/ /app/law-updater/scripts/
COPY src/ /app/law-updater/src/

# ── Stage 2: runtime ────────────────────────────────
FROM python:3.13-slim-bookworm

WORKDIR /app/law-updater

COPY --from=builder /app/law-updater/.venv /app/law-updater/.venv
COPY --from=builder /app/law-updater/config/ /app/law-updater/config/
COPY --from=builder /app/law-updater/scripts/ /app/law-updater/scripts/
COPY --from=builder /app/law-updater/src/ /app/law-updater/src/

ENV PATH="/app/law-updater/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
