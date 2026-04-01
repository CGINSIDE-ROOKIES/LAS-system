# AI Legal Support System (LAS) Monorepo

AI 기반 법무지원 시스템 프로젝트입니다.
주요 법령에 대한 질의응답(Q&A), 계약서 법률 검토, 계약서 초안 작성 기능을 제공하는 PoC(Proof of Concept) 시스템을 목표로 합니다.

## Overview

본 프로젝트는 근로기준법, 하도급거래 공정화에 관한 법률 등 주요 법령 및 관련 문서를 기반으로,
사용자가 자연어로 질문하면 관련 법령 조문과 근거를 바탕으로 답변을 제공하는 AI 법무지원 시스템입니다.

또한 계약서 업로드를 통해 법률 검토를 수행하고,
빈 양식과 입력 정보를 바탕으로 계약서 초안을 자동 작성하는 기능을 포함합니다.

## Monorepo Structure

- `apps/frontend`: Next.js 기반 프론트엔드 앱
- `apps/backend/api`: FastAPI 백엔드 서버
- `apps/backend/rag`: RAG 파이프라인 패키지 (retrieval + generation)
- `apps/backend/legal-pipeline`: 법령 데이터 수집 및 임베딩 파이프라인
- `apps/backend/doc-processor`: 계약서 문서 처리 및 분석
- `packages/eslint-config`: 프론트 공유 ESLint 설정
- `packages/tsconfig`: 프론트 공유 TypeScript 설정

## Key Features

- 법령 및 관련 문서 기반 질의응답
- 하이브리드 검색(Vector + Keyword)
- 답변 근거 조문/출처 제공
- Q&A 이력 저장 및 조회
- 계약서 업로드 및 법률 검토
- 계약서 초안 자동 작성

## Scope

### 대상 법령
- 근로기준법
- 근로기준법 시행령 / 시행규칙
- 하도급거래 공정화에 관한 법률 및 시행령
- 기간제근로자법
- 파견근로자법 등

### 대상 문서
- 근로계약서
- 하도급계약서
- HWP / HWPX / DOC / DOCX / PDF 문서

## Tech Stack

### Backend
- FastAPI

### Frontend
- Next.js

### Search / Data
- Qdrant
- OpenSearch
- PostgreSQL
- Neo4j

### LLM
- OpenAI API
- Google Gemini API
- KT midm API (도입 예정)

## Docs

- 프론트 로컬 실행/개발 가이드: `apps/frontend/README.md`
- 백엔드 전체 구조: `apps/backend/README.md`
- API 서버 실행/엔드포인트: `apps/backend/api/README.md`
- RAG 파이프라인 CLI/인덱싱: `apps/backend/rag/README.md`
- 법령 데이터 파이프라인: `apps/backend/legal-pipeline/README.md`

## Quick Start

### Frontend

> 모든 명령어는 프로젝트 루트에서 실행합니다.

```bash
corepack enable
corepack prepare pnpm@9.12.3 --activate
pnpm install
cp apps/frontend/.env.example apps/frontend/.env
pnpm --filter @las/frontend dev
```

접속: `http://localhost:3000`

### Backend

```bash
cd apps/backend/api
cp .env.example .env   # 최초 1회
uv run uvicorn main:app --reload
```

상세 설정은 `apps/backend/api/README.md` 참조.
