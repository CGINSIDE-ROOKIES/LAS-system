# RAG 파이프라인 검색 품질 저하 — 검토 의견서

> 작성일: 2026-04-14  
> 최종 수정: 2026-04-16  
> 검토 대상: RAG Trace 상세 조사 보고서 (2026-04-14)  
> 검토 범위: `apps/backend/rag/`, `apps/backend/api/`

---

## 1. 개요

전달받은 trace 상세 조사 보고서의 Finding 7개와 부가 관찰 1건에 대해 코드 수준에서 직접 확인하였습니다.  
각 항목에 대해 코드상 근거를 특정하고, 수정 방향 및 현재 처리 상태를 정리합니다.

---

## 2. 심각도 높음

### F1. `legal_relation` 코퍼스가 Qdrant와 OpenSearch 사이에서 분리 운영된다

**코드 확인**

- Qdrant `legal_relation`: 약 100,269건 (`law_to_case` 98,900 / `law_to_law` 1,369)
- OpenSearch `legal_relation`: 수백 건 수준, `case_to_case`만 존재

ingest 경로가 파이프라인별로 달라 두 백엔드가 서로 다른 subset을 보유하고 있다.

- `legal-pipeline/scripts/embed_qdrant_3collections.py:30` — COLLECTIONS에 `legal_relation` 미포함
- `law-updater/scripts/embed_qdrant_3collections.py:30` — `legal_relation` 포함

**영향**

같은 코퍼스를 전제로 하는 RRF 융합 자체가 성립하지 않는다. Qdrant에만 존재하는 `law_to_case` / `law_to_law` 문서가 OpenSearch 쪽에서는 등장하지 않으므로 융합 점수가 왜곡되고 결과 재현성이 낮아진다.

**수정 방향**

RAG 코드 단독 수정으로 해결 불가. Qdrant와 OpenSearch 중 단일 진실 소스를 결정한 뒤 ingest 파이프라인을 정렬해야 한다.  
단기 대응: OpenSearch `OPENSEARCH_INDEX`에서 `legal_relation`을 제외해 Qdrant 단독 검색으로 전환.

**처리 상태: 미처리 (인프라/데이터 결정 선행 필요)**

---

### F2. 규범형 질의에서도 법령이 처음부터 상위에 오르지 못한다

**코드 확인**

`generation/pipeline.py:191` — `case_law` intent일 때만 검색 범위를 강하게 바꾼다.  
`normative` intent는 전체 코퍼스 RRF 후 최소 law 보강 구조를 그대로 유지한다.

`retrieval/service.py:37` — `law_boost_score=0.003`  
`retrieval/ranking.py:56` — law doc에만 소량 가산점 부여. 실질적 순위 변화를 만들기엔 값이 작다.

**런타임 증거**

질문 `연장근로 최대 시간은 몇 시간인가요?` (intent=normative) 최종 컨텍스트:  
1위 `expc`, 2위 `expc`, 3위 `prec`, 4위 `prec`, 5위 `law` — `law_context_status=supplemented`

BM25 `law_article` 단독 1위는 `근로기준법 제56조`였지만 RRF 융합 후 뒤로 밀렸다.  
즉, 판례/해석례가 먼저 선택된 뒤 최소 개수를 맞추기 위해 법령이 뒤늦게 보강되는 구조다.

**수정 방향**

`normative` intent에서 `law_article` 컬렉션 가중치를 높이거나 law filter를 더 강하게 적용하는 정책 추가.  
`law_boost_score=0.003`의 실효성을 eval로 검증하고 값 조정 또는 방식 변경 검토 필요.

**처리 상태: 부분 처리**  
intent 기반 필터 전략 적용(6~8차)으로 `case_law` rel 0.699 → 0.954 개선. `normative` 추가 조정 미완료. 8차 기준 law_hit=0.600으로 40%에서 올바른 법령 문서를 찾지 못하고 있다.

---

## 3. 심각도 중간

### F3. Qdrant `law_names` 필터가 soft filter에 가깝다

**코드 확인**

`retrieval/qdrant.py:61` — `law_names`를 `should`로 구성.  
`retrieval/qdrant.py:63` — 주석에 "일부 환경에서 should가 scoring에만 관여할 수 있음" 직접 명시.

OpenSearch는 `minimum_should_match=1`로 hard filter. 두 백엔드 간 필터 강도가 다르다.

**영향**

법령 필터를 지정한 검색에서도 Qdrant 결과에 unrelated hit가 섞일 수 있다.  
동일 조건임에도 Qdrant와 OpenSearch 동작이 달라 RRF 융합 점수 일관성이 낮아진다.

**수정 방향**

`law_names` 조건을 `must` 안에 중첩 `should`로 감싸 hard filter로 전환:

```json
{
  "must": [
    {"key": "doc_type", "match": {"any": [...]}},
    {
      "should": [
        {"key": "law_name", "match": {"any": ["법령명"]}},
        {"key": "root_law_name", "match": {"any": ["법령명"]}},
        {"key": "related_law_name", "match": {"any": ["법령명"]}},
        {"key": "related_law_names", "match": {"any": ["법령명"]}}
      ]
    }
  ]
}
```

실제 운영 Qdrant 버전에서 중첩 `should` 동작 검증 필요.

**처리 상태: 미처리**

---

### F4. duplicate suffix 규칙이 ingest와 retrieval 사이에서 불일치한다

**코드 확인**

ingest — `dataset_builder.py:622` — 중복 id를 `::dupN` 형태로 생성.  
retrieval — `retrieval/common.py:187` — `__dupN`(언더스코어 두 개) 패턴만 제거.

```python
# 실제 ingest 포맷과 불일치
return re.sub(r"__dup\d+$", "", source_id)
```

**영향**

정규화 함수가 실제 suffix를 제거하지 못해 같은 문서 family의 중복 청크가 별개 문서로 취급된다.  
RRF merge에서 유사 청크가 과대표집돼 top-k에 중복이 노출될 수 있다.

**수정 방향**

`normalize_source_id()`의 정규식을 `::dup\d+$`로 수정. ingest 실제 suffix 패턴 재확인 후 확정.

**처리 상태: 미처리**

---

### F5. `legal_relation` ranking 메타데이터가 retrieval에서 사용되지 않는다

**코드 확인**

ingest 단계에서 relation row에 다음 메타데이터가 부여된다.

- `default_score_multiplier`
- `relation_model_priority`
- `retrieval_role`

근거: `legal-pipeline/scripts/embed_qdrant_3collections.py:34`, `:292`

retrieval은 이를 전혀 참조하지 않는다. Qdrant + BM25 RRF, `law_boost(+0.003)`, law context 최소 개수 보강만 수행한다.

근거: `generation/pipeline.py:302`, `retrieval/ranking.py:56`

**영향**

supporting/trace 용도로 설계된 relation 문서가 primary evidence(법령 조문, 판례)와 동등하게 경쟁해 top-k 슬롯을 차지한다.

**수정 방향**

`retrieval_role` 또는 `relation_model_priority` 기준으로 supporting 역할 문서 score에 multiplier를 적용하거나 top-k 내 개수를 제한한다.

**처리 상태: 보류**  
8차 eval 기준 context_precision이 0.707~0.711로 intent 전반 수렴 중이며 현재 병목으로 확인되지 않음. F1(코퍼스 분리) 해소 후 relation 문서 비중 변화를 재측정한 뒤 재검토.

---

## 4. 심각도 낮음

### F6. `law_article.appendix` dense vector가 RAG 경로에서 사용되지 않는다

**코드 확인**

Qdrant `law_article`은 named vector 2개를 보유한다.
- `body`: 조문 본문
- `appendix`: 부칙/별표/첨부

근거: `legal-pipeline/scripts/upload/indexing.py:46`

RAG 런타임은 컬렉션당 vector name 하나만 사용한다.

`generation/pipeline.py:231` — `vector_name=(rcfg.qdrant_vector_name_map or {}).get(collection)`  
기본값: `law_article=body`

**영향**

별표·부칙 기반 질문(최저임금 적용 제외 기준, 산재보험 급여표 등)에서 dense recall 저하.  
`appendix` 내용은 BM25 fallback에만 의존한다.

**수정 방향**

`appendix` vector를 별도 검색 경로로 추가하거나 `body`와 weighted sum으로 결합하는 방식 검토.  
`appendix` 질의 비중 파악 선행 필요.

**처리 상태: 미처리 (우선순위 낮음)**

---

### F7. `OPENSEARCH_INDEX`가 단일 문자열로 multi-index path를 처리한다

**코드 확인**

`retrieval/service.py:25`, `generation/pipeline.py:248` — `OPENSEARCH_INDEX`를 단일 `index_name` 문자열로 처리.  
런타임 환경변수: `OPENSEARCH_INDEX=law_article,legal_case,legal_relation`

OpenSearch는 쉼표 구분 multi-index path를 허용하므로 동작 자체는 한다.

**영향**

코드상 "단일 인덱스 설정값"과 "복수 인덱스 path"가 혼용돼 유지보수 혼란 요소가 된다.

**수정 방향**

`OPENSEARCH_INDEX`를 리스트로 파싱해 명시적으로 multi-index를 지원하도록 수정.

**처리 상태: 미처리 (우선순위 낮음)**

---

## 5. 처리 현황 요약

| # | 내용 | 심각도 | 처리 상태 |
|---|------|--------|-----------|
| F1 | `legal_relation` 코퍼스 Qdrant·OpenSearch 분리 | 높음 | 미처리 (인프라 결정 필요) |
| F2 | 규범형 질의 법령 우선 retrieval 미작동 | 높음 | 부분 처리 (`case_law` 완료, `normative` 미완) |
| — | `article_no` retrieval 미반영 | 높음 | **처리 완료** (제거, `ac90774`) |
| F3 | Qdrant `law_names` soft filter | 중간 | 미처리 |
| F4 | duplicate suffix ingest·retrieval 불일치 | 중간 | 미처리 |
| F5 | `legal_relation` ranking 메타데이터 미활용 | 중간 | 보류 (F1 해소 후 재검토) |
| F6 | `law_article.appendix` vector 미사용 | 낮음 | 미처리 |
| F7 | `OPENSEARCH_INDEX` 단일 문자열 처리 | 낮음 | 미처리 |

---

## 6. 결론

`article_no` 제거 외에 처리 완료된 항목은 없다. F2는 `case_law` 영역만 부분 개선됐다.

8차 eval 기준으로 즉시 효과가 기대되는 순서:

1. **F4 — duplicate suffix 정규식 수정**: 변경 범위가 한 줄 수준이며 중복 청크 과대표집을 직접 차단한다.
2. **F3 — Qdrant law_names hard filter 전환**: OpenSearch와 필터 일관성 확보, law filter precision 개선 기대.
3. **F2 — normative retrieval 추가 조정**: law_hit 0.600 개선의 핵심 방향.
4. **F1 — legal_relation 코퍼스 단일화**: 외부 협의 필요하나 RRF 융합 신뢰성 회복을 위한 근본 조치.
