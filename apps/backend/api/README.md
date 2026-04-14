# las-api

Legal AI Assistant FastAPI 백엔드 서버.

## 사전 준비

- Qdrant·OpenSearch는 서버에서 운영 중. `.env`에 연결 정보 설정 필요.
- PostgreSQL 연결 정보도 `.env`에 설정 필요.

## 실행

반드시 이 디렉토리(`apps/backend/api/`)에서 실행한다.

```bash
cd apps/backend/api
cp .env.example .env   # 최초 1회
uv run uvicorn main:app --reload    # 개발 서버 (localhost:8000)
```

## 환경변수

`.env` 파일에 아래 항목을 설정한다.

```env
# PostgreSQL
DATABASE_URL=postgresql://...

# 로그 레벨 (기본: INFO)
LOG_LEVEL=INFO

# Qdrant — 서버 연결 정보
QDRANT_URL=http://<서버IP>:6333
QDRANT_COLLECTIONS=law_article,legal_case,legal_relation
# QDRANT_API_KEY=

# OpenSearch — 서버 연결 정보
OPENSEARCH_URL=http://<서버IP>:9200
OPENSEARCH_INDEX=las_legal_docs

# 임베딩 (API only)
EMBEDDING_MODEL=text-embedding-3-large
OPENAI_API_KEY=...
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_EMBEDDING_DIMENSIONS=

# LLM
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
LLM_MAX_TOKENS=4096
```

앱 버전(`FastAPI version`)은 `apps/backend/api/pyproject.toml`의 `project.version`을 읽어 사용한다.

## 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/health` | 서버 상태 확인 |
| `POST` | `/api/v1/qa/ask` | Q&A 단일 응답 |
| `POST` | `/api/v1/qa/ask/stream` | Q&A SSE 스트리밍 응답 |
| `GET` | `/api/v1/qa/history` | Q&A 히스토리 목록 |
| `GET` | `/api/v1/qa/history/{id}` | 히스토리 단건 조회 |
| `DELETE` | `/api/v1/qa/history/{id}` | 히스토리 단건 삭제 |
| `DELETE` | `/api/v1/qa/history` | 히스토리 다건 삭제 |
| `POST` | `/api/v1/qa/{id}/feedback` | 답변 피드백 제출 (👍/👎) |

### POST /api/v1/qa/ask

요청:
```json
{
  "question": "연장근로 최대 시간은?",
  "doc_types": ["law"],
  "law_filter": ["근로기준법"]
}
```
`doc_types`, `law_filter`는 선택 항목.

응답:
```json
{
  "answer": "...",
  "retrieved_docs": [...],
  "law_context_status": "ok"
}
```

### POST /api/v1/qa/ask/stream

요청 바디는 `/ask`와 동일. SSE 스트림으로 응답한다.

```
data: {"type": "chunk", "content": "연장근로는"}
data: {"type": "chunk", "content": " 주 12시간을"}
data: {"type": "done", "retrieved_docs": [...], "law_context_status": "ok", "qa_id": "..."}
data: {"type": "error", "code": "EMBEDDING_ERROR", "error": "..."}
data: {"type": "error", "code": "LLM_TIMEOUT", "error": "..."}
data: {"type": "error", "code": "LLM_ERROR", "error": "..."}
data: {"type": "error", "code": "PIPELINE_ERROR", "error": "..."}
```

## 에러 코드

### 공통(JSON)

| code | HTTP status | 설명 |
|---|---:|---|
| `VALIDATION_ERROR` | 422 | 요청 바디/쿼리 유효성 오류 |
| `HTTP_ERROR` | 가변 | 라우터에서 명시적으로 raise한 HTTPException |
| `EMBEDDING_ERROR` | 503 | 임베딩 단계 오류 |
| `LLM_TIMEOUT` | 504 | LLM 요청 타임아웃 |
| `LLM_ERROR` | 502 | LLM 호출/응답 파싱 오류 |
| `PIPELINE_ERROR` | 503 | 기타 retrieval 파이프라인 오류 |
| `INTERNAL_ERROR` | 500 | 서버 내부 오류 |

### 스트리밍(SSE)

`/api/v1/qa/ask/stream`의 오류 이벤트는 아래 형식이다.

```text
data: {"type":"error","code":"EMBEDDING_ERROR|LLM_TIMEOUT|LLM_ERROR|PIPELINE_ERROR|INTERNAL_ERROR","error":"..."}
```

### POST /api/v1/qa/{id}/feedback

요청:
```json
{
  "thumbs_up": true,
  "comment": "도움이 됐어요"
}
```
`comment`는 선택 항목. 동일 `qa_id` 재제출 시 덮어씀 (upsert).

응답 (`201 Created`):
```json
{ "id": "<feedback_uuid>" }
```
