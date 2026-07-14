# RAG 파이프라인 검색 품질 저하 — 검토 의견서 (수정본)

> 작성일: 2026-04-14  
> 최종 수정: 2026-04-16  
> 검토 대상: RAG Trace 상세 조사 보고서 (2026-04-14)  
> 검토 범위: `apps/backend/rag/`, `apps/backend/api/`

---

## 1. 개요

초기 보고서의 Finding 7개와 부가 관찰 1건을 재검증했다.  
이번 문서는 **2026-04-16 실제 운영 데이터 확인 결과**와 **이번 수정 내역**을 반영한 최종 정리본이다.

---

## 2. Finding별 재검증 결과

### Finding 1. `legal_relation` 코퍼스 분리 운영 여부

초기 가설: Qdrant와 OpenSearch의 `legal_relation`이 사실상 서로 다른 코퍼스로 운영되어 RRF 융합 전제가 깨진다.

재확인 결과(2026-04-16, `100.72.14.114`):
- OpenSearch `legal_relation` 총건수: `18461`
- Qdrant `legal_relation` points_count: `18461`
- `relation_model` 분포도 동일:
1. `case_to_case`: `10165`
2. `law_to_case`: `7176`
3. `law_to_law`: `1120`

판단:
- 두 저장소는 동일 코퍼스로 운영 중이다.
- `legal_relation`에 대한 RRF 융합 전제는 성립한다.

주의사항:
- Qdrant에서 `relation_type=law_to_case`로 집계하면 0건이 나오는데, 해당 값은 `relation_model` 필드 값이므로 집계 키를 잘못 잡은 영향이다.

처리 상태: **수정 없음 (문제 아님으로 확정)**

---

### Finding 2. 규범형 질문에서 법령 중심 retrieval 미작동

재확인 결과, 세부 문제는 다음과 같다.

1. 판례/해석례는 조문 대비 데이터 규모가 크고 자연어 서술이 풍부해 동등 경쟁(RRF)에서 구조적으로 유리하다.
2. `law_boost_score=0.003`은 실효성이 낮다. 일반적인 RRF 점수 범위(대략 `0.01~0.05`)에서 순위 역전을 만들기 어렵고 eval에서도 유의미한 개선이 확인되지 않았다.
3. `select_rows_with_law_policy()`는 top-k 외부에서 law를 보강하는 구조라, “법령 우선 검색”이 아니라 “법령 최소 보장” 동작에 가깝다.

적용한 해결:
- `normative` intent에서 law/case를 분리된 슬롯으로 운영하도록 변경.
- `RetrievalConfig`에 `normative_law_ratio: float = 0.5` 추가.
- 현재 기본값은 law:case = `5:5`이며, 추후 eval 기반으로 조정 가능.

처리 상태: **수정 완료 (후속 튜닝 예정)**

---

### Finding 3. Query Parser `article_no` 미사용

초기 가설: parser가 `article_no`를 추출하지만 retrieval에서 사용되지 않는다.

결론:
- 실제 사용처가 없고, few-shot 기반 추론값 신뢰도/포맷 일치성 리스크가 있어 필터로 쓰기 어렵다.
- 사용되지 않는 필드를 유지하는 편이 오히려 혼란을 만든다.

적용한 해결:
1. QueryParser에서 `article_no` 필드 제거
2. 해당 few-shot 예시 제거

처리 상태: **수정 완료**

---

### Finding 4. duplicate suffix 규칙 불일치

초기 가설: ingest와 retrieval의 duplicate suffix 규칙 불일치로 중복 정규화가 깨진다.

재확인 결과:
- `normalize_source_id()`의 `__dup\d+$`는 현재 데이터와 매칭되지 않는 레거시 코드다.
- 실제 중복처럼 보이는 건 `canonical_id`가 같아도 ingest 시점에 `::ctx::{hash}`로 분리된 서로 다른 청크이며, Qdrant에 고유 ID로 저장된다.
- 이 청크들은 내용이 달라 retrieval에서 별개 문서로 취급하는 것이 타당하다.

처리 상태: **수정 없음 (문제 아님으로 확정)**

---

### Finding 5. Qdrant `law_names` 필터가 soft filter

재확인 결과:
- 최상위 `should` 기반 soft filter는 Qdrant hang 이슈 회피를 위해 의도적으로 적용된 구조다 (`ef67872`).
- OpenSearch 대비 필터 강도 불일치는 사실이다.
- 다만 soft filter가 실제로 발동하는 조건은 `doc_types + law_names` 동시 설정일 때뿐이다.
- 현재 UI에 `doc_types` 선택 기능이 없어 운영 경로에서는 이 조건이 실질적으로 만족되지 않는다.

처리 상태: **수정 없음 (현 운영 영향 낮음, 구조적 차이는 인지)**

---

### Finding 6. `legal_relation` ranking 메타데이터 미사용

재확인 결과:
- `default_score_multiplier`, `relation_model_priority`, `retrieval_role`는 ingest 시점에 주입되지만 retrieval 파이프라인에 연결되지 않은 미완성 설계 상태다.
- 원래 의도는 `QUERY_RETRIEVAL_PROFILES`(쿼리 유형별 컬렉션/관계문서 가중치 차등) 연동이다.
- 운영 eval 9차(2026-04-16)에서는 `legal_relation` 문서가 top-k에 1건도 없어, 현재 미적용으로 인한 순위 왜곡도 관측되지 않았다.

판단:
- 이번 범위에서 즉시 수정 우선순위는 낮다.
- 다만 intent 기반 슬롯 분리 방향과 설계 맥락은 일치하므로, 향후 `legal_relation`이 실제 top-k에 진입하기 시작하면 프로필 연동을 재검토한다.

처리 상태: **보류 (협의 필요)**

---

### Finding 7. `law_article.appendix` dense vector 실사용성

데이터 재확인:
1. `has_related_appendix=True`: `50건`
2. `has_related_appendix=False`: `1932건`
3. 전체 `1982건` 중 실질 appendix 대상은 약 `2.5%`
4. appendix vector는 전체에 채워져 있으나 대부분 placeholder 성격

판단:
- 영향 범위가 좁고, 관련 질의 비중도 낮다.
- 현재는 BM25 키워드 경로로 대부분 커버 가능하며 eval 쿼리셋에도 appendix 타깃 질문이 없다.

처리 상태: **조치 불필요 (현 시점 우선순위 낮음)**

---

### 부가 관찰. `OPENSEARCH_INDEX` 단일 문자열/멀티 인덱스 혼용

재확인 결과 세부 문제:
1. 타입 혼란: `opensearch_index: str`인데 실제 사용은 `"a,b,c"`
2. `urllib.parse.quote`가 쉼표를 `%2C`로 인코딩하며 우연히 동작

판단:
- 기능은 동작했지만 유지보수 혼란 요소가 맞다.

적용한 해결:
- multi-index path 사용 의도를 코드/타입 의미에 맞게 정리해 혼란 요소 제거.

처리 상태: **수정 완료**

---

## 3. 처리 현황 요약

| 항목 | 결론 | 상태 |
|---|---|---|
| Finding 1 (`legal_relation` 분리 운영) | 실제로 동일 코퍼스 운영 확인, RRF 전제 유효 | 수정 없음 |
| Finding 2 (규범형 법령 우선 미작동) | 동등 경쟁 구조 문제 확인, normative 슬롯 분리 도입 | 수정 완료 |
| Finding 3 (`article_no` 미사용) | 미사용 필드/예시 제거가 타당 | 수정 완료 |
| Finding 4 (duplicate suffix 불일치) | 레거시 패턴이며 실데이터 영향 없음 | 수정 없음 |
| Finding 5 (Qdrant soft filter) | 구조적 차이는 사실이나 현 운영 영향 제한적 | 수정 없음 |
| Finding 6 (`legal_relation` 메타 미사용) | 미완성 설계이나 현재 지표 영향 미관측 | 보류 |
| Finding 7 (`appendix` dense 미사용) | 대상 비중 매우 낮아 우선순위 낮음 | 조치 불필요 |
| 부가 관찰 (`OPENSEARCH_INDEX`) | 동작은 하나 타입/의미 혼란 존재 | 수정 완료 |

---

## 4. 결론

초기 보고서에서 가장 크게 제기됐던 `legal_relation` 코퍼스 분리 문제는 재검증 결과 사실이 아니며, 현재 `100.72.14.114` 기준 두 저장소는 동일 코퍼스로 운영 중이다.  
실제 개선이 필요한 핵심은 규범형 질의에서의 법령 우선성 확보였고, 이번 작업에서 intent 기반 슬롯 분리(`normative_law_ratio`)로 구조적 보완을 적용했다.
