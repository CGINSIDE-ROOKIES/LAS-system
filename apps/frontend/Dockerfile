# Build context: apps/frontend
# The pnpm-lock.yaml here is the old monorepo root lockfile (importers: '.' = turbo,
# 'apps/frontend' = this app, 'packages/*' = shared packages). We reconstruct that
# workspace structure inside Docker since packages/ is outside the build context.
# ── Stage 1: deps ────────────────────────────────────
FROM node:20-alpine AS deps

RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

# Workspace root: lockfile importers expect '.' = turbo-only root
WORKDIR /app

# Root package.json matches the lockfile's '.' importer (just turbo)
RUN printf '{"private":true,"devDependencies":{"turbo":"^2.1.3"}}\n' > package.json

# pnpm-workspace.yaml mirrors the original monorepo layout
RUN printf 'packages:\n  - "apps/frontend"\n  - "packages/*"\n' > pnpm-workspace.yaml

# Lockfile was moved from monorepo root; it still encodes the root-relative structure
COPY pnpm-lock.yaml ./

# @las/tsconfig is the only workspace devDep the frontend uses.
# It is pure JSON config; reproduce the actual file contents here.
RUN mkdir -p packages/tsconfig && \
    printf '{"name":"@las/tsconfig","version":"0.0.1","private":true}\n' \
        > packages/tsconfig/package.json && \
    printf '{"$schema":"https://json.schemastore.org/tsconfig","compilerOptions":{"target":"ES2022","module":"ESNext","moduleResolution":"Bundler","strict":true,"skipLibCheck":true,"esModuleInterop":true,"resolveJsonModule":true,"forceConsistentCasingInFileNames":true}}\n' \
        > packages/tsconfig/base.json && \
    printf '{"extends":"./base.json","compilerOptions":{"jsx":"preserve","allowJs":false,"noEmit":true,"incremental":true,"lib":["dom","dom.iterable","esnext"],"plugins":[{"name":"next"}]}}\n' \
        > packages/tsconfig/react-next.json

# Stub the other workspace packages so pnpm can resolve the full lockfile
RUN mkdir -p packages/eslint-config && \
    printf '{"name":"@las/eslint-config","version":"0.0.1","private":true,"type":"module"}\n' \
        > packages/eslint-config/package.json && \
    mkdir -p packages/ui && \
    printf '{"name":"@las/ui","version":"0.0.1","private":true,"type":"module","main":"./src/index.tsx","types":"./src/index.tsx","peerDependencies":{"react":"^18.3.1"}}\n' \
        > packages/ui/package.json

# Frontend package.json goes to the 'apps/frontend' importer path expected by lockfile
COPY package.json apps/frontend/package.json

RUN pnpm install --frozen-lockfile

# ── Stage 2: build ───────────────────────────────────
FROM node:20-alpine AS builder

RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

WORKDIR /app

# Restore installed modules (order matters: copy before source so layers don't conflict)
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/frontend/node_modules ./apps/frontend/node_modules
COPY --from=deps /app/packages ./packages

# Copy all frontend sources into the workspace sub-path (.dockerignore excludes node_modules/.next)
COPY . apps/frontend/

# Reconstruct workspace root files (not present in build context)
RUN printf '{"private":true,"devDependencies":{"turbo":"^2.1.3"}}\n' > package.json && \
    printf 'packages:\n  - "apps/frontend"\n  - "packages/*"\n' > pnpm-workspace.yaml
COPY turbo.json ./
COPY pnpm-lock.yaml ./

RUN pnpm --filter @las/frontend build \
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

# outputFileTracingRoot=../../ from apps/frontend/next.config.mjs resolves to /app/,
# so standalone mirrors the full workspace tree: node_modules/, apps/frontend/server.js, etc.
COPY --from=builder /app/apps/frontend/.next/standalone ./
COPY --from=builder /app/apps/frontend/.next/static ./apps/frontend/.next/static
COPY --from=builder /app/apps/frontend/public ./apps/frontend/public

EXPOSE 3000

CMD ["node", "apps/frontend/server.js"]
