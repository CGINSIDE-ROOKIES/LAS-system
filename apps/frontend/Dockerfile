# Build context: apps/frontend (context path is relative to project root in Coolify)
#
# Workspace root = apps/frontend (pnpm-workspace.yaml lives here).
# Workspace packages at ../../packages/* — in Docker that resolves to /app/packages/*.
# outputFileTracingRoot = path.join(__dirname, "../../") = /app/, so the standalone
# output mirrors /app/ and server.js ends up at apps/frontend/server.js inside it.
#
# ── Stage 1: deps ────────────────────────────────────
FROM node:20-alpine AS deps

RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

# Place the app at apps/frontend so that ../../packages/* resolves to /app/packages/*
# (matching outputFileTracingRoot and the lockfile's ../../packages/* importer paths)
WORKDIR /app/apps/frontend

# Create workspace package stubs at the path pnpm expects (../../ from WORKDIR)
# @las/tsconfig is a devDep used by tsc; reproduce its actual JSON files here.
RUN mkdir -p /app/packages/tsconfig && \
    printf '{"name":"@las/tsconfig","version":"0.0.1","private":true}\n' \
        > /app/packages/tsconfig/package.json && \
    printf '{"$schema":"https://json.schemastore.org/tsconfig","compilerOptions":{"target":"ES2022","module":"ESNext","moduleResolution":"Bundler","strict":true,"skipLibCheck":true,"esModuleInterop":true,"resolveJsonModule":true,"forceConsistentCasingInFileNames":true}}\n' \
        > /app/packages/tsconfig/base.json && \
    printf '{"extends":"./base.json","compilerOptions":{"jsx":"preserve","allowJs":false,"noEmit":true,"incremental":true,"lib":["dom","dom.iterable","esnext"],"plugins":[{"name":"next"}]}}\n' \
        > /app/packages/tsconfig/react-next.json

# Stub the other workspace packages (no deps from frontend, just need to exist)
RUN mkdir -p /app/packages/eslint-config && \
    printf '{"name":"@las/eslint-config","version":"0.0.1","private":true,"type":"module"}\n' \
        > /app/packages/eslint-config/package.json && \
    mkdir -p /app/packages/ui && \
    printf '{"name":"@las/ui","version":"0.0.1","private":true,"type":"module","main":"./src/index.tsx","types":"./src/index.tsx","peerDependencies":{"react":"^18.3.1"}}\n' \
        > /app/packages/ui/package.json

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./

RUN pnpm install --frozen-lockfile

# ── Stage 2: build ───────────────────────────────────
FROM node:20-alpine AS builder

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

WORKDIR /app

# Restore workspace packages (symlinks in node_modules point to /app/packages/*)
COPY --from=deps /app/packages ./packages
COPY --from=deps /app/apps/frontend/node_modules ./apps/frontend/node_modules

# Copy all frontend sources (.dockerignore excludes local build artifacts)
COPY . ./apps/frontend/

RUN cd apps/frontend && node_modules/.bin/next build

# ── Stage 3: runtime ────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production

# standalone mirrors /app/ — contains node_modules/, apps/frontend/server.js, etc.
COPY --from=builder /app/apps/frontend/.next/standalone ./
COPY --from=builder /app/apps/frontend/.next/static ./apps/frontend/.next/static
COPY --from=builder /app/apps/frontend/public ./apps/frontend/public

EXPOSE 3000

CMD ["node", "apps/frontend/server.js"]
