# Langfuse 관측성 가이드

> 대상 코드: `apps/backend/rag/rag_pipeline/observability/`, `apps/backend/rag/eval/run_eval.py`
> 작성일: 2026-04-09

---

## 1. 개요

LAS 시스템은 Langfuse를 통해 RAG 파이프라인의 각 단계를 trace로 기록하고, eval 실행 후 RAGAS 메트릭 점수를 해당 trace에 연결한다. 이를 통해 **실시간 요청 디버깅**과 **평가 결과의 trace 연결 분석** 두 가지 용도로 활용한다.

Langfuse 비활성 시(환경변수 미설정) 모든 trace/score 호출은 no-op으로 동작하여 파이프라인에 영향을 주지 않는다.

---

## 2. 현재 기록되는 데이터

### 2-1. Trace 구조

```
trace: eval_run  (eval 실행) / qa_request  (API 요청)
│  input : question, intent
│  output: answer, law_context_status
│
├── span: retrieval
│   │  input : question, doc_types, law_names, intent
│   │  output: 선택된 docs 수, law_context_status
│   │
│   ├── span: embed
│   │      input : model, provider
│   │      output: dim (벡터 차원 수)
│   │
│   ├── span: qdrant
│   │      input : collections, candidate_k
│   │      output: hits[] (컬렉션별 검색 결과 수)
│   │
│   ├── span: opensearch
│   │      input : index, candidate_k
│   │      output: hits 수 (실패 시 error)
│   │
│   ├── span: fusion
│   │      input : rrf_k, candidate_k, auto_law_boost
│   │      output: fused_docs 수 (RRF 융합 후)
│   │
│   └── span: ranking
│          input : top_k, min_law_contexts
│          output: selected_docs 수, law_context_status
│
└── generation span: generation
       model, temperature, max_tokens
       input : 프롬프트 전문 (컨텍스트 + 질문)
       output: 답변 텍스트
       usage : input_tokens, output_tokens
```

### 2-2. eval 실행 후 push되는 Scores

eval(`python eval/run_eval.py`) 실행 시 각 trace에 다음 score가 추가된다.

| score 이름 | 범위 | 측정 조건 | comment |
|---|---|---|---|
| `answer_relevancy` | 0~1 | contexts 있는 전 건 | < 0.5 시 쿼리 텍스트 (100자) |
| `context_precision` | 0~1 | contexts 있는 전 건 | — |
| `faithfulness` | 0~1 | answer_relevancy < 0.6 대상만 | < 0.5 시 쿼리 텍스트 (100자) |
| `law_hit` | 0 또는 1 | gold_law가 있는 건 | — |

---

## 3. Langfuse에서 확인 가능한 것

### 3-1. Trace 목록 / 개별 Trace

- **질문 → 답변 전체 흐름**: 어느 단계에서 얼마나 걸렸는지 타임라인으로 확인
- **retrieval 단계 세부**: Qdrant 컬렉션별 hit 수, OpenSearch hit 수, fusion 후 문서 수, ranking 후 최종 문서 수
- **law_context_status**: `ok` / `case_only` / `missing` / `supplemented` — 컨텍스트 구성 상태
- **에러 trace**: level=ERROR로 기록된 trace만 필터링해 실패 요청 원인 파악

### 3-2. 토큰 사용량 및 비용

generation span에 `usage_details`로 다음이 기록된다(`service.py:106`).

```python
usage = {"input": N, "output": N, "total": N}
```

| 항목 | 의미 | 활용 |
|---|---|---|
| `input` tokens | 프롬프트 전체 토큰 수 (컨텍스트 + 질문) | 컨텍스트가 너무 긴 요청 식별 |
| `output` tokens | 생성된 답변 토큰 수 | 장문 답변 발생 패턴 파악 |
| `total` tokens | input + output | 요청당 비용 추정 기준 |

**Langfuse에서 확인 가능한 뷰**

- **개별 trace** → generation span 클릭 → Usage 탭: 해당 요청의 토큰 상세
- **Dashboard** → Token Usage 집계: 일별/모델별 총 토큰 수 추세
- **모델 단가 설정** 시 토큰 수 → 비용(USD)으로 자동 환산

**활용 예시**

- `input_tokens`가 비정상적으로 높은 trace → 컨텍스트 truncation이 안 됐거나 retrieved docs가 과다한 것 → retrieval span의 `selected_docs` 수와 함께 확인
- 동일 질의 유형에서 `input_tokens` 편차가 크다면 → `law_context_status`와 교차 분석 (`supplemented` 상태가 토큰을 더 소비)
- eval 배치 실행 후 `total_tokens` 합산 → 실제 평가 비용 추적

### 3-3. 레이턴시

span의 시작/종료 시각은 Langfuse가 자동으로 기록한다. 단계별로 확인 가능한 내용:

| span | 확인 가능한 레이턴시 |
|---|---|
| `embed` | 임베딩 모델 호출 시간 |
| `qdrant` + `opensearch` | 두 검색이 병렬 실행되므로 각각의 실제 소요 시간 |
| `generation` | LLM 응답 시간 (스트리밍 시 첫 토큰~마지막 토큰까지) |
| trace 전체 | 사용자 체감 응답 시간 |

### 3-4. Scores 탭 (eval 결과 연결)

- eval 실행 후 각 trace에 RAGAS score가 붙어 있어, **어떤 질문이 낮은 점수를 받았는지** trace와 함께 확인 가능
- `answer_relevancy < 0.5` 또는 `faithfulness < 0.5`인 trace는 comment에 쿼리 텍스트가 기록되어 목록에서 바로 식별 가능
- `law_hit=0`인 trace는 gold_law 문서가 retrieval에서 누락된 건 — retrieval span의 qdrant/opensearch hit 수와 함께 보면 원인 파악 가능

### 3-3. 필터 활용 예시

| 확인하고 싶은 것 | Langfuse 필터 |
|---|---|
| retrieval 실패 요청 | level = ERROR, span name = retrieval |
| 저품질 답변 | score: answer_relevancy < 0.5 |
| 환각 의심 | score: faithfulness < 0.5 |
| 법령 retrieval 미스 | score: law_hit = 0 |
| case_only 응답 | output.law_context_status = case_only |

---

## 4. 활용 시나리오

### A. 신규 질의 유형 디버깅

사용자 질문이 이상한 답변을 반환할 때:
1. Langfuse trace 목록에서 해당 질문 검색
2. retrieval span → qdrant/opensearch hit 수 확인 → 검색 자체가 0건인지
3. ranking span → `law_context_status` 확인 → `missing`이면 retrieval 실패, `case_only`면 판례만 나온 것
4. generation span → 프롬프트 전문 확인 → 어떤 컨텍스트가 LLM에 전달됐는지

### B. eval 결과와 trace 연결 분석

`python eval/run_eval.py` 실행 후:
1. Langfuse Scores 탭에서 `answer_relevancy` 기준 오름차순 정렬
2. 저점수 trace 클릭 → comment에 기록된 쿼리 확인
3. retrieval span의 `law_context_status`, hit 수 → retrieval 문제인지 generation 문제인지 판단
4. `faithfulness`가 낮으면 generation span의 프롬프트·답변 확인 → 환각 여부 검토

### C. 파이프라인 변경 전후 비교

개선 적용 후 eval을 재실행하면:
- 이전 실행 trace group vs 새 trace group의 score 분포 비교
- 특정 intent(`normative` / `case_law` / `mixed`) 필터 후 score 추세 확인
- `law_hit` 변화로 retrieval 개선 여부 결정론적으로 검증

---

## 5. 환경 설정

```bash
# apps/backend/rag/.env
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=https://cloud.langfuse.com  # self-hosted 시 변경
```

두 키 중 하나라도 없으면 Langfuse 전체가 자동 비활성화된다(`langfuse_client.py:18`).

---

## 6. 관련 파일

| 파일 | 역할 |
|---|---|
| `rag_pipeline/observability/langfuse_client.py` | 클라이언트 싱글톤 초기화, `score_trace()` |
| `rag_pipeline/observability/tracing.py` | `start_trace/span`, `end_span`, `update_trace`, `get_trace_id` |
| `rag_pipeline/generation/pipeline.py` | 파이프라인 각 단계에서 span 생성/종료 |
| `eval/run_eval.py` | eval trace 생성 및 RAGAS score push |
