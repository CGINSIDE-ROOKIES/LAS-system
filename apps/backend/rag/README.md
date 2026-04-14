# rag-pipeline

retrieval/generation 파이프라인 패키지.

`rag-pipeline` 패키지로 빌드되며, `apps/backend/api/`가 이 패키지를 라이브러리로 의존한다.

## 현재 상태

- Qdrant·OpenSearch 데이터는 서버에서 운영 중이며, 로컬 인덱싱 없이 바로 연결해 사용한다.
- 로컬 Docker(Qdrant/OpenSearch)는 더 이상 사용하지 않는다.
- `.env`에 서버 연결 정보를 설정하면 바로 검색·평가가 가능하다.

---

## 빠른 시작

1. 작업 디렉토리 이동
```bash
cd /home/user/projects/LAS-system/apps/backend/rag
```

2. 환경변수 로드
```bash
cp .env.example .env   # 최초 1회, 서버 연결 정보 입력
set -a && source .env && set +a
```

3. 검색 실행
```bash
uv run python cli/query_hybrid_rrf.py --question "연장근로 최대 시간은 몇 시간인가요?" --top-k 5
```

---

## 검색 실행

Qdrant:
```bash
uv run python cli/query_qdrant_topk.py --question "연장근로 최대 시간은?" --top-k 5
```
BM25:
```bash
uv run python cli/query_opensearch_bm25.py --question "연장근로 최대 시간은?" --top-k 5
```
Hybrid RRF:
```bash
uv run python cli/query_hybrid_rrf.py --question "연장근로 최대 시간은?" --top-k 5
```
통합 (LLM 컨텍스트 출력 포함):
```bash
uv run python cli/query_all_retrieval.py --question "연장근로 최대 시간은?" --top-k 5 --llm-context-text
```
LLM Generator 단독 호출:
```bash
uv run python cli/generator.py --prompt "안녕"
```
Retrieval + Generator 통합:
```bash
uv run python cli/generate_answer.py --question "연장근로 최대 시간은?" --top-k 5
```

---

## 평가

골드셋 기반 Hit@k 평가:
```bash
uv run python cli/evaluate_retrieval_gold.py --top-k 5
uv run python cli/evaluate_retrieval_gold.py --top-k 5 --out-csv cli/retrieval_eval_result.csv
```

---

## 환경변수

### 검색 서버 연결

```env
QDRANT_URL=http://...
QDRANT_API_KEY=...

OPENSEARCH_URL=http://...
OPENSEARCH_USER=...
OPENSEARCH_PASSWORD=...
```

### 임베딩

임베딩은 OpenAI-compatible API 경로만 사용한다.

```env
EMBEDDING_MODEL=text-embedding-3-large
OPENAI_API_KEY=...
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_EMBEDDING_DIMENSIONS=
```

`OPENAI_EMBEDDING_DIMENSIONS`를 지정하는 경우 Qdrant에 저장된 벡터 차원과 반드시 일치해야 한다.

### LLM (generation CLI 사용 시)

```env
# openai_compat (기본값)
LLM_PROVIDER=openai_compat
LLM_CHAT_COMPLETIONS_URL=http://...
LLM_MODEL=...
LLM_API_KEY=...

# Gemini 사용 시
# LLM_PROVIDER=gemini
# GEMINI_API_KEY=...
# GEMINI_MODEL=gemini-1.5-flash
```

---

## source_id 필드 기준

| 필드 | 설명 |
|---|---|
| `source_id` | 운영·표시 권장. 정규화 기준 (`__dupN` suffix 제거) |
| `source_id_raw` | 원본 source id (디버깅용) |
| `source_id_normalized` | 중복 제거·병합 기준으로 사용한 정규화 id |

---

## 주요 스크립트

| 스크립트 | 설명 |
|---|---|
| `cli/query_qdrant_topk.py` | Qdrant Top-K 검색 |
| `cli/query_opensearch_bm25.py` | OpenSearch BM25 검색 |
| `cli/query_hybrid_rrf.py` | Qdrant + BM25 RRF 병합 |
| `cli/query_all_retrieval.py` | 통합 실행 + LLM 컨텍스트 출력 |
| `cli/generator.py` | LLM 단독 호출 유틸 |
| `cli/generate_answer.py` | Retrieval → Generation 통합 실행 |
| `cli/evaluate_retrieval_gold.py` | 골드셋 기반 Hit@k 평가 |
