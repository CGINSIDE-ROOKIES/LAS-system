# Backend

LAS(Legal AI Assistant) 백엔드. 법령 기반 Q&A API와 RAG 파이프라인으로 구성된다.

---

## 구성

| 디렉토리 | 역할 |
|---|---|
| `api/` | FastAPI 기반 HTTP API 서버 |
| `rag/` | 검색·생성 파이프라인 패키지 (`api`가 라이브러리로 의존) |
| `doc-processor/` | 문서 전처리 (추후 정리 예정) |
| `law-updater/` | 법령 업데이트 (추후 정리 예정) |
| `legal-pipeline/` | 법령 데이터 파이프라인 (추후 정리 예정) |

---

## api

FastAPI 서버. `rag` 패키지를 in-process 라이브러리로 사용해 Q&A 요청을 처리하고, 결과를 PostgreSQL에 저장한다.

### 실행

```bash
cd apps/backend/api
cp .env.example .env   # 최초 1회
uv run uvicorn main:app --reload
```

### 주요 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/health` | 서버 상태 확인 |
| `POST` | `/api/v1/qa/ask` | Q&A 단일 응답 |
| `POST` | `/api/v1/qa/ask/stream` | Q&A SSE 스트리밍 응답 |
| `GET` | `/api/v1/qa/history` | Q&A 히스토리 목록 |
| `GET` | `/api/v1/qa/history/{id}` | 히스토리 단건 조회 |
| `DELETE` | `/api/v1/qa/history/{id}` | 히스토리 단건 삭제 |
| `DELETE` | `/api/v1/qa/history` | 히스토리 다건 삭제 |
| `POST` | `/api/v1/qa/{id}/feedback` | 답변 피드백 제출 (👍/👎, upsert) |

### DB 마이그레이션

서버 시작 시 Alembic이 자동으로 `alembic upgrade head`를 실행한다.
기존 DB에 처음 적용할 때는 아래 명령으로 현재 상태를 등록해야 한다.

```bash
uv run alembic stamp 0001
```

### 상세 문서

- API 상세: [`api/README.md`](api/README.md)
- DB 스키마: [`rag/docs/04_db_schema.md`](rag/docs/04_db_schema.md)
- 기능 명세: [`rag/docs/01_frd.md`](rag/docs/01_frd.md)
- 아키텍처: [`rag/docs/02_architecture.md`](rag/docs/02_architecture.md)

---

## rag

검색·생성 파이프라인 패키지. Qdrant 벡터 검색과 OpenSearch BM25를 RRF로 병합하고 LLM으로 답변을 생성한다.

Qdrant·OpenSearch는 서버에서 운영 중이며, `.env`에 연결 정보를 설정해 바로 사용한다.

### 검색 테스트

```bash
cd apps/backend/rag
set -a && source .env && set +a

uv run python cli/query_hybrid_rrf.py --question "연장근로 최대 시간은?" --top-k 5
uv run python cli/generate_answer.py --question "연장근로 최대 시간은?" --top-k 5
```

### 상세 문서

- 피드백 활용: [`../../../docs/feedback-utilization.md`](../../../docs/feedback-utilization.md)
