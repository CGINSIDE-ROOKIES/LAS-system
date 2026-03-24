# Build context: repo root (needs packages/*, pnpm-workspace.yaml, pnpm-lock.yaml)
# ── Stage 1: deps ────────────────────────────────────
FROM node:20-alpine AS deps

RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

WORKDIR /app

# Copy workspace root manifests
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./

# Copy workspace packages needed by frontend
COPY packages/ packages/
COPY apps/frontend/package.json apps/frontend/package.json

RUN pnpm install --frozen-lockfile

# ── Stage 2: build ───────────────────────────────────
FROM node:20-alpine AS builder

RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/packages/ ./packages/
COPY --from=deps /app/apps/frontend/node_modules ./apps/frontend/node_modules
COPY apps/frontend/ apps/frontend/
COPY turbo.json package.json pnpm-workspace.yaml ./

RUN pnpm --filter frontend build \
    && echo "=== standalone root ===" \
    && ls -la apps/frontend/.next/standalone/ \
    && echo "=== standalone node_modules (top-level) ===" \
    && ls apps/frontend/.next/standalone/node_modules/ | head -20 \
    && echo "=== standalone apps/frontend (should exist with experimental.outputFileTracingRoot) ===" \
    && ls -la apps/frontend/.next/standalone/apps/frontend/ \
    && echo "=== standalone node_modules (.pnpm should be present) ===" \
    && ls apps/frontend/.next/standalone/node_modules/ | head -5

# ── Stage 3: runtime ────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production

# outputFileTracingRoot=monorepo root means standalone mirrors the full tree:
#   node_modules/ (with .pnpm), apps/frontend/server.js, apps/frontend/.next/
COPY --from=builder /app/apps/frontend/.next/standalone ./
COPY --from=builder /app/apps/frontend/.next/static ./apps/frontend/.next/static
COPY --from=builder /app/apps/frontend/public ./apps/frontend/public

EXPOSE 3000

CMD ["node", "apps/frontend/server.js"]
