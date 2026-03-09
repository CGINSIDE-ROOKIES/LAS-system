# LAS System Monorepo

## Structure

- `apps/frontend`: Next.js 기반 프론트엔드 앱
- `apps/backend`: Python 백엔드 앱
- `packages/ui`: 프론트 공유 UI 컴포넌트
- `packages/eslint-config`: 프론트 공유 ESLint 설정
- `packages/tsconfig`: 프론트 공유 TypeScript 설정

## Frontend Local Setup

### 1) 설치해야 하는 것들

- `Node.js` 18.17 이상 (권장: 20 LTS)
- `corepack` (Node.js에 포함)
- `pnpm` 9.12.3 (`packageManager` 버전과 동일)

### 2) 의존성 설치

```bash
cd /home/user/projects/LAS-system
corepack enable
corepack prepare pnpm@9.12.3 --activate
pnpm install
```

### 3) 프론트엔드 로컬 실행

```bash
cd /home/user/projects/LAS-system
pnpm --filter @las/frontend dev
```

- 접속 주소: `http://localhost:3000`

### 4) 화면/스타일이 이상할 때 (캐시 초기화)

```bash
cd /home/user/projects/LAS-system
pkill -f "next dev|turbo" || true
rm -rf apps/frontend/.next
pnpm install --no-frozen-lockfile
pnpm --filter @las/frontend dev
```

### 5) 자주 쓰는 명령어

```bash
pnpm --filter @las/frontend build
pnpm --filter @las/frontend start
pnpm --filter @las/frontend lint
pnpm --filter @las/frontend typecheck
```

## Backend Run

```bash
cd /home/user/projects/LAS-system/apps/backend
uv run main.py
```
