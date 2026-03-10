# LAS System Monorepo

## Structure

- `apps/frontend`: Next.js 기반 프론트엔드 앱
- `apps/backend`: Python 백엔드 앱
- `packages/ui`: 프론트 공유 UI 컴포넌트
- `packages/eslint-config`: 프론트 공유 ESLint 설정
- `packages/tsconfig`: 프론트 공유 TypeScript 설정

## Frontend Docs

- 프론트 로컬 실행/개발 가이드: `apps/frontend/README.md`

## Backend Run

```bash
cd /home/user/projects/LAS-system/apps/backend
uv run main.py
```
