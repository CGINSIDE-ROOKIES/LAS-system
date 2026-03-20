# las-api

Legal AI Assistant FastAPI 백엔드 서버.

## 사전 준비

- `apps/backend/rag/`의 Docker 스토어(Qdrant/OpenSearch)가 실행 중이어야 한다.
- `.env` 파일에 환경변수가 설정되어 있어야 한다.

## 실행

반드시 이 디렉토리(`apps/backend/api/`)에서 실행한다.

```bash
cd apps/backend/api
cp ../rag/.env.example .env   # 최초 1회 — LLM 환경변수 추가 필요 (하단 참조)

uv run dev      # 개발 서버 (--reload)
uv run start    # 운영 서버
```

## 환경변수

`.env` 파일에 아래 항목을 설정한다. Qdrant/OpenSearch 항목은 `../rag/.env.example`을 복사해 채운다.

```env
# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=las_legal_docs
# QDRANT_API_KEY=

# OpenSearch
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_INDEX=las_legal_docs
# OPENSEARCH_API_KEY=
# OPENSEARCH_USERNAME=
# OPENSEARCH_PASSWORD=

# 임베딩 모델
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

# LLM — openai_compat (기본값)
LLM_PROVIDER=openai_compat
LLM_CHAT_COMPLETIONS_URL=http://...
LLM_MODEL=...
LLM_API_KEY=...

# LLM — Gemini 사용 시
# LLM_PROVIDER=gemini
# GEMINI_API_KEY=...
# GEMINI_MODEL=gemini-1.5-flash
```

## 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 서버 상태 확인 |
| POST | `/api/v1/qa/ask` | Q&A 단일 응답 |
| POST | `/api/v1/qa/ask/stream` | Q&A SSE 스트리밍 응답 |

### POST /api/v1/qa/ask

요청:
```json
{
  "question": "연장근로 최대 시간은?",
  "doc_types": ["law"],
  "law_names": ["근로기준법"]
}
```
`doc_types`, `law_names`는 선택 항목이다.

응답:
```json
{
  "answer": "...",
  "sources": [{"source_id": "...", "doc_type": "...", "law_name": "...", "rank": 1, "score": 0.9}],
  "retrieved_docs": [...],
  "law_context_status": "ok",
  "law_context_added": false
}
```

### POST /api/v1/qa/ask/stream

요청 바디는 `/ask`와 동일. SSE 스트림으로 응답한다.

```
data: {"type": "chunk", "content": "연장근로는"}
data: {"type": "chunk", "content": " 주 12시간을"}
data: {"type": "done"}
```
