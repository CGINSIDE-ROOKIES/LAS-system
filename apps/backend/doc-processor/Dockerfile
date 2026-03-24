# Build context: apps/backend/doc-processor/
# ── Stage 1: build ───────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS builder

# git: needed for python-hwpx (git dep)
# default-jdk-headless: needed for jpype1 compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    git default-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml uv.lock ./
COPY doc_processor/ doc_processor/

RUN uv sync --frozen --no-dev

# ── Stage 2: runtime ────────────────────────────────
FROM python:3.12-slim-bookworm

# JRE for bundled vendor/hwp2hwpx JAR
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/doc_processor/ /app/doc_processor/
COPY --from=builder /build/pyproject.toml /app/pyproject.toml
COPY langgraph.json /app/langgraph.json
COPY ci/ /app/ci/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8123

CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "8123", "--no-browser"]
