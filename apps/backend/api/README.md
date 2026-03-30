# las-api

Legal AI Assistant FastAPI 백엔드 서버.

## 사전 준비

- OpenSearch가 로컬 Docker에서 실행 중이어야 한다.
- Qdrant는 외부 서버에 컬렉션(`law_article`, `legal_case`, `legal_relation`)이 준비되어 있어야 한다.
- `.env` 파일에 환경변수가 설정되어 있어야 한다.

## 실행

반드시 이 디렉토리(`apps/backend/api/`)에서 실행한다.

```bash
cd apps/backend/api
cp ../rag/.env.example .env   # 최초 1회 — QDRANT_URL, GEMINI_API_KEY 등 채워야 함

uv run uvicorn main:app --reload                    # 개발 서버
uv run uvicorn main:app --host 0.0.0.0 --port 8000  # 운영 서버
```

## 환경변수

`.env` 파일에 아래 항목을 설정한다. 전체 항목은 `../rag/.env.example` 참조.

```env
# Qdrant — 외부 서버 IP로 변경 필요
QDRANT_URL=http://<서버IP>:6333
QDRANT_COLLECTIONS=law_article,legal_case,legal_relation
# QDRANT_API_KEY=

# OpenSearch — 로컬 Docker
OPENSEARCH_URL=http://localhost:9200
OPENSEARCH_INDEX=las_legal_docs

# 임베딩 provider (sentence_transformers | openai)
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-mpnet-base-v2
# OpenAI 사용 시: EMBEDDING_PROVIDER=openai, EMBEDDING_MODEL=text-embedding-3-large, OPENAI_API_KEY=...

# LLM — Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
LLM_MAX_TOKENS=4096
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
