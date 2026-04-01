# RAG 파이프라인 동작 흐름 문서

> 대상 코드: `apps/backend/api/`, `apps/backend/rag/`
> 작성일: 2026-04-01

---

## 1. 전체 흐름 개요

```
클라이언트
  │  POST /api/v1/qa/ask (또는 /ask/stream)
  ▼
[qa.py] API 라우터
  │  1. QueryParser → 질문 구조화 (법령명, intent, is_legal)
  │  2. is_legal=false → 조기 반환
  │  3. RagPipeline.run() / .stream() 호출
  ▼
[pipeline.py] RagPipeline._retrieve()
  │  4. embed_query() → 질문 임베딩 벡터 생성
  │  5. 병렬 검색: Qdrant(벡터) + OpenSearch(BM25)
  │  6. fuse_rrf_multi() → Qdrant 컬렉션 간 RRF 융합
  │  7. fuse_rrf() → Qdrant + OpenSearch 하이브리드 RRF 융합
  │  8. apply_law_boost() → 규범형 질의 시 law 문서 점수 가산
  │  9. select_rows_with_law_policy() → top_k 선택 + law 최소 보장
  │ 10. build_llm_context_rows/text() → 프롬프트용 컨텍스트 빌딩
  ▼
[pipeline.py] build_user_prompt_with_limit()
  │ 11. system_prompt + context + question 조립
  ▼
[llm_client.py] GenerationService.generate() / .stream()
  │ 12. LLM API 호출 (OpenAI 호환 또는 Gemini)
  ▼
[qa.py] 응답 반환 + DB 저장 (save_qa)
```

---

## 2. 단계별 상세 설명

### 2-1. API 라우터 (`api/src/routers/qa.py`)

**엔드포인트**

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/qa/ask` | 단일 JSON 응답 |
| POST | `/api/v1/qa/ask/stream` | SSE 스트리밍 응답 |

**요청 바디 (`AskRequest`)**

```json
{
  "question": "연차 수당 계산 기준은?",
  "session_id": "optional-uuid",
  "doc_types": ["law", "prec"],     // null이면 전체
  "law_names": ["근로기준법"]        // null이면 파서 결과 사용
}
```

`doc_types` 허용값: `law`, `prec`, `detc`, `decc`, `expc`

**응답 (`AskResponse`)**

```json
{
  "answer": "...",
  "retrieved_docs": [
    {
      "rank": 1,
      "source_id": "law_article::...",
      "doc_type": "law",
      "law_name": "근로기준법",
      "article_no": "제60조",
      "score": 0.031746,
      "snippet": "...",
      "text": "..."
    }
  ],
  "law_context_status": "ok"   // "ok" | "missing" | "supplemented" | "irrelevant"
}
```

**스트리밍 SSE 이벤트 순서**

```
data: {"type": "status", "code": "EMBEDDING_COLD_START", ...}   // 첫 요청 시만
data: {"type": "chunk", "content": "답변 토큰..."}               // 반복
data: {"type": "done", "retrieved_docs": [...], "law_context_status": "ok", "qa_id": "uuid"}
data: {"type": "error", "code": "PIPELINE_ERROR", "error": "..."}  // 오류 시
```

---

### 2-2. Query Parser (`rag/rag_pipeline/query_parser/parser.py`)

LLM(기본: `gemini-2.0-flash-lite`)으로 질문을 구조화한다.

**출력 (`QueryParseResult`)**

```python
@dataclass
class QueryParseResult:
    law_names: list[str]    # 정식 법령명 목록 (약칭 → 정식명 변환 포함)
    article_no: str         # "제60조" 형태로 정규화
    intent: str | None      # "normative" | "case_law" | "mixed" | None
    is_legal: bool          # 법률 무관이면 False → 파이프라인 조기 반환
    parser_fallback: bool   # 파싱 실패 시 True (is_legal=True로 fallback)
```

**intent 별 파이프라인 동작 차이**

| intent | law_names 필터 | law 문서 강제 보강 |
|--------|---------------|------------------|
| `normative` | 적용 | 적용 (`enforce=True`) |
| `mixed` | 적용 | 해제 (`enforce=False`) |
| `case_law` | 해제 (`None` 처리) | 해제 |
| `None` (fallback) | 적용 | 적용 |

---

### 2-3. 임베딩 (`rag/rag_pipeline/retrieval/common.py`)

```python
vector = embed_query(
    question,
    embedding_model,          # 기본: EMBEDDING_MODEL 환경변수
    provider="sentence_transformers" | "openai",
    ...
)
```

- `sentence_transformers` 사용 시 로컬 모델 로드 (첫 요청에 cold start 30~90초)
- `is_embedding_model_cached()` 로 cold start 여부 감지 → 스트리밍 시 `EMBEDDING_COLD_START` 이벤트 선발행

---

### 2-4. 병렬 검색 (`pipeline.py` → `retrieval/qdrant.py`, `retrieval/opensearch.py`)

`ThreadPoolExecutor`로 Qdrant(복수 컬렉션) + OpenSearch를 동시에 검색한다.

```python
with ThreadPoolExecutor() as executor:
    qdrant_futures = [executor.submit(_qdrant_task, col) for col in collections]
    bm25_future = executor.submit(_bm25_task)  # opensearch_url이 있을 때만
```

**Qdrant 벡터 검색 (`search_qdrant_with_vector`)**
- 미리 계산한 벡터를 그대로 전달해 재임베딩 없이 복수 컬렉션 병렬 검색
- `doc_types`, `law_names` 필터를 Qdrant 쿼리 필터로 변환
- `fetch_multiplier=2`: 중복 제거 여유분 확보를 위해 `candidate_k * 2` 개 fetch
- `dedup=True`: source_id 정규화 기준 중복 제거

**OpenSearch BM25 검색 (`search_bm25`)**
- 키워드 기반 검색 (한국어 형태소 분석 인덱스 가정)
- `fetch_multiplier=5`: BM25 노이즈 특성상 더 많이 fetch 후 필터링
- `opensearch_url`이 없으면 BM25 검색 스킵

**설정값 (기본)**

| 파라미터 | 기본값 | 설명 |
|----------|--------|------|
| `top_k` | 5 | 최종 LLM 입력 문서 수 |
| `candidate_k` | 30 | 각 검색 백엔드에서 가져올 후보 수 |
| `rrf_k` | 60 | RRF 순위 편향 상수 |
| `timeout` | 120초 | 검색 API 타임아웃 |

---

### 2-5. RRF 융합 (`rag/rag_pipeline/retrieval/fusion.py`)

**Qdrant 컬렉션 간 융합 (`fuse_rrf_multi`)**

복수 컬렉션 결과를 먼저 RRF로 합산한다.

```
score(doc) = Σ  1 / (rrf_k + rank_i)    (컬렉션 수만큼 합산)
```

컬렉션이 1개이면 bypass.

**Qdrant + OpenSearch 융합 (`fuse_rrf`)**

```
score(doc) = 1/(60 + rank_qdrant)  +  1/(60 + rank_opensearch)
```

- 두 백엔드 모두에서 검색된 문서는 점수가 누적되어 상위 랭크
- 동점 tie-break 순서: ① rrf_score 내림차순 ② 등장 백엔드 수 내림차순 ③ 백엔드 내 최고 rank 오름차순 ④ source_id 오름차순

**문서 동일성 판별 키 (`_rrf_key`)**

```python
# source_id 있으면: suffix 제거 정규화
normalize_source_id(source_id)
# 없으면: 텍스트 앞 800자의 SHA-1
f"text::{sha1(text[:800])}"
```

---

### 2-6. 순위 조정 (`rag/rag_pipeline/retrieval/ranking.py`)

**Law 문서 점수 가산 (`apply_law_boost`)**

규범형 질의 (`기준`, `요건`, `의무`, `절차` 등 키워드 포함 시) 에만 적용:

```python
if doc_type == "law":
    score += law_boost_score   # 기본 0.003
```

가산 후 재정렬하여 rank 재부여.

**Law 문서 최소 보장 (`select_rows_with_law_policy`)**

```
1. top_k 내 law 문서 수 ≥ min_law_contexts(기본 1)?
   → "ok" 반환
2. enforce=True 이고 law 부족?
   → top_k 바깥에서 law 문서를 끌어와 최하위 non-law 문서와 교체
   → 교체 성공: "supplemented", 실패: "missing"
3. enforce=False 이고 law 부족?
   → "missing" 반환 (프롬프트에 경고 문구 삽입)
```

`law_context_status`는 최종 응답에 포함되어 클라이언트가 신뢰도를 판단할 수 있게 한다.

---

### 2-7. 컨텍스트 빌딩 (`rag/rag_pipeline/retrieval/context.py`)

**`build_llm_context_rows`**
- 각 문서 텍스트를 `max_content_chars`(기본 1200자) 이내로 자름
- 자를 때 조문 경계(제N조/제N항) → 문장 경계 → 공백 경계 순으로 의미 단위 보존
- `max_total_chars`(기본 6000자) 초과 시 이후 문서 스킵

**`build_llm_context_text`**
- LLM 안정성을 위해 `law → expc → prec → decc → detc` 순서로 정렬
- 출력 형식:

```
[질문]
{question}

[메타]
- law_context_added: true
- context_docs: 5

[참고 법령 및 판례]
1. (law) law_name=근로기준법 | source_id=law_article::...
{조문 내용}

2. (prec) law_name=근로기준법 | source_id=prec::...
{판례 내용}
```

---

### 2-8. 프롬프트 조립 (`pipeline.py`)

```python
def build_user_prompt_with_limit(
    retrieved_context_text,
    question,
    max_input_chars=6000,
    law_context_status,
):
```

- `law_context_status == "missing"`: 프롬프트 앞에 "근거 부족 명시" 경고 삽입
- `max_input_chars` 초과 시 context를 잘라내고 질문은 반드시 포함

**System Prompt (기본값)**
- 노동법·하도급법 전문 어시스턴트 역할 정의
- 컨텍스트 외 사실 추측 금지
- 3~5문장 이내 간결한 답변

---

### 2-9. LLM 호출 (`rag/rag_pipeline/generation/llm_client.py`)

두 가지 provider를 지원한다.

#### OpenAI 호환 (`openai_compat`)

```
POST {LLM_CHAT_COMPLETIONS_URL}
Authorization: Bearer {LLM_API_KEY}
{
  "model": "{LLM_MODEL}",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user",   "content": "context + question"}
  ],
  "max_tokens": 2048,
  "temperature": 0.2,
  "stream": true   // 스트리밍 시
}
```

스트리밍: SSE `data: {...}` 라인에서 `choices[0].delta.content` 추출

#### Gemini (`gemini`)

```
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}
{
  "contents": [{"role": "user", "parts": [{"text": "..."}]}],
  "systemInstruction": {"parts": [{"text": "..."}]},
  "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}
}
```

스트리밍: `:streamGenerateContent?alt=sse` 엔드포인트 사용, `candidates[0].content.parts[].text` 추출

---

### 2-10. DB 저장 (`api/src/history.py`)

답변이 비어있지 않으면 PostgreSQL에 저장:

```python
save_qa(conn,
    question=...,
    answer=...,
    law_context_status=...,
    retrieved_docs=[...],
    session_id=...,
)
```

스트리밍 응답은 모든 청크 수집 완료 후 `done` 이벤트 직전에 저장.
저장 실패는 로깅만 하고 응답에 영향 없음.

---

## 3. 환경변수 정리

| 변수 | 설명 | 예시 |
|------|------|------|
| `QDRANT_URL` | Qdrant 서버 URL | `http://qdrant:6333` |
| `QDRANT_COLLECTIONS` | 검색 컬렉션 목록 (콤마 구분) | `law_article,legal_case` |
| `QDRANT_VECTOR_NAME_MAP` | 컬렉션별 named vector 매핑 | `law_article=body` |
| `QDRANT_API_KEY` | Qdrant API 키 (옵션) | |
| `OPENSEARCH_URL` | OpenSearch URL (없으면 BM25 스킵) | `http://opensearch:9200` |
| `OPENSEARCH_INDEX` | BM25 검색 인덱스명 | `las_laws` |
| `EMBEDDING_MODEL` | 임베딩 모델명 | `jhgan/ko-sroberta-multitask` |
| `EMBEDDING_PROVIDER` | `sentence_transformers` \| `openai` | `sentence_transformers` |
| `LLM_PROVIDER` | `openai_compat` \| `gemini` | `openai_compat` |
| `LLM_CHAT_COMPLETIONS_URL` | OpenAI 호환 엔드포인트 | `http://vllm:8000/v1/chat/completions` |
| `LLM_MODEL` | 모델명 | `Qwen/Qwen2.5-7B-Instruct` |
| `LLM_API_KEY` | LLM API 키 | |
| `GEMINI_API_KEY` | Gemini API 키 (query_parser + Gemini LLM 공용) | |
| `QUERY_PARSER_MODEL` | Query Parser 모델 (기본: `gemini-2.0-flash-lite`) | |

---

## 4. 오류 처리

| 상황 | HTTP 코드 | SSE 이벤트 |
|------|-----------|------------|
| Qdrant/OpenSearch 연결 실패 | 502 | `type: error, code: PIPELINE_ERROR` |
| 내부 서버 오류 | 500 | `type: error, code: INTERNAL_ERROR` |
| 법률 무관 질문 | 200 (정상) | `law_context_status: irrelevant` |
| law 문서 부족 | 200 (정상) | `law_context_status: missing` |
| Query Parser 실패 | 200 (fallback) | `parser_fallback: true` (로그에만 기록) |
