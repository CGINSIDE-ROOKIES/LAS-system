# RAG 최적화 작업 — Before 기준값

> 작성일: 2026-04-15  
> 브랜치: `refactor/rag-optimization`  
> 목적: 최적화 작업 전후 수치 비교를 위한 현재 상태 기록

---

## 1. 지연 시간 (Langfuse Observation Percentiles)

| Span | p50 | p90 | p95 | p99 |
|------|-----|-----|-----|-----|
| qa_request | 8.92s | 12.68s | 14.74s | 16.44s |
| retrieval | 7.71s | 9.60s | 10.37s | 11.39s |
| opensearch | 7.49s | 9.01s | 9.72s | 10.96s |
| qdrant | 5.85s | 7.38s | 8.08s | 8.93s |
| embed | 0.20s | 0.70s | 1.03s | 1.25s |
| query_parse | 0.92s | 8.01s | 10.78s | 49.75s |
| generation | — | — | — | — |

**병목 요인**

- **OpenSearch (p50 7.49s)**: `kr_legal_nori` 형태소 분석기가 index/search analyzer 동일 적용되어 쿼리마다 형태소 분석 오버헤드 발생. 인덱스 매핑에서 `search_analyzer` 분리 필요 (인프라 작업).
- **Qdrant (p50 5.85s)**: OpenSearch와 병렬 실행되어 현재는 묻히지만 OpenSearch 수정 후 차기 병목이 됨.
- **query_parse (p99 49.75s)**: 특정 쿼리에서 LLM 타임아웃으로 추정되는 극단적 tail latency 존재. 하드 타임아웃 미설정.
- **HTTP 커넥션 재사용 없음**: `urllib.request` 사용으로 요청마다 TCP 핸드쉐이크 발생 → `urllib3.PoolManager`로 교체 완료 (이 브랜치).

---

## 2. 평가 품질 (RAGAS, eval_set 전체 43건)

> eval_set 순서 재정렬 후 전체 실행. 1건 irrelevant 제외, n=40 평가.

| 메트릭 | 점수 |
|--------|------|
| answer_relevancy | **0.831** (n=40) |
| context_precision | **0.710** (n=40) |
| faithfulness | **0.875** (n=2, 저점수 대상) |
| law_hit | **0.600** (n=35) |

| intent | n | answer_relevancy | context_precision |
|--------|---|-----------------|------------------|
| normative | 20 | 0.811 | 0.711 |
| case_law | 12 | 0.876 | 0.707 |
| mixed | 8 | 0.812 | 0.710 |

- `law_context_status`: ok 24건, case_only 14건, missing 4건, irrelevant 1건
- 저점수(answer_relevancy 0.0) 2건: 임금 체불 법적 책임, 육아휴직 거부 제재

---

## 3. Langfuse 누적 점수 (99개 trace 기준)

| 점수명 | n | avg | 0점 | 1점 |
|--------|---|-----|-----|-----|
| law_context_quality | 99 | 0.80 | 4 | 63 |
| context_precision | 10 | 0.64 | 1 | 3 |
| law_hit | 10 | 0.60 | 4 | 6 |
| answer_relevancy | 10 | 0.89 | 0 | 0 |

---

## 4. 코드 변경 사항 (이 브랜치)

| 파일 | 변경 내용 |
|------|----------|
| `retrieval/common.py` | `urllib.request` → `urllib3.PoolManager` (커넥션 재사용, stale connection 자동 재시도) |
| `generation/pipeline.py` | ranking span에 `law_count`/`non_law_count`, retrieval span에 `context_chars` 추가, `law_context_quality` score 자동 push |

---

## 5. 미해결 과제 (after 작업 대상)

| 항목 | 담당 |
|------|------|
| OpenSearch `search_analyzer` 분리 (`kr_legal_nori` → `whitespace`) + 재인덱싱 | 인프라 |
| `query_parse` 하드 타임아웃 추가 | 코드 |
| mixed context_precision 개선 (컨텍스트 비율 조정) | 코드 |
| Qdrant 지연 원인 추가 분석 | 코드/인프라 |
