# RAG 파이프라인 검색 품질 저하 — 검토 의견서

> 작성일: 2026-04-14
> 검토 대상: RAG Trace 상세 조사 보고서 (2026-04-14)
> 검토 범위: `apps/backend/rag/`, `apps/backend/api/`

---

## 1. 개요

전달받은 trace 상세 조사 보고서의 내용을 실제 코드 수준에서 직접 확인하였습니다. 보고서에서 지목한 4가지 원인 각각에 대해 코드상 근거를 특정하고, 수정이 필요한 위치와 방향을 정리합니다.

---

## 2. 원인별 코드 검토 및 수정 방향

### 원인 1. BM25가 유사 청크를 상위권으로 올린다

**코드 확인**

`retrieval/opensearch.py:63-65`

```python
must: list[dict[str, Any]] = [
    {"match": {search_text_field: {"query": query, "operator": "or"}}}
]
```

`operator: "or"`는 질문 토큰 중 일부만 매칭되어도 문서를 후보로 올린다. "퇴직급여", "퇴직수당"처럼 여러 사건에 반복 등장하는 용어가 있으면 해당 구절을 공유하는 청크가 일괄적으로 상위권에 집중된다.

또한 `fetch_multiplier=5`(`opensearch.py:103`)로 `top_k`의 5배를 가져오도록 설정되어 있어, 유사 청크가 대량으로 후보에 유입된다.

**수정 방향**

- `operator: "or"` → `operator: "and"` 또는 `minimum_should_match`를 높여 매칭 기준을 강화한다.
- `fetch_multiplier`를 5에서 2~3으로 낮춰 BM25 후보 수를 줄인다. 현재 주석에도 "BM25에서 중복/유사 청크가 많이 섞이는 경향을 감안해 넉넉히 확보하기 위한 값"이라고 명시되어 있으나, 이로 인해 유사 청크 유입이 심화되고 있다.

---

### 원인 2. 현재 dedup은 near-duplicate를 걸러내지 못한다

**코드 확인**

`retrieval/common.py:276-308` — `dedup_normalized_rows()`

```python
def normalize_source_id(source_id: str) -> str:
    return re.sub(r"__dup\d+$", "", source_id)
```

`retrieval/fusion.py:23-34` — `_rrf_key()`

```python
sid = str(row.get("source_id", "") or "")
key = normalize_source_id(sid) if sid else ""
if key:
    return key
# source_id가 없을 때만 텍스트 해시 fallback
text = str(row.get("text", "") or "")
return f"text::{_sha1_hex(text[:800].encode('utf-8'))}"
```

`source_id`가 있으면 텍스트 내용은 전혀 보지 않는다. 이번 케이스의 3개 청크(`detc::26493::13`, `detc::29633::13`, `detc::26294::12`)는 모두 서로 다른 `source_id`를 가지므로 dedup을 통과한다. 텍스트 유사도가 86%에 달해도 별개 문서로 취급한다.

또한 `normalize_source_id()`는 `__dup\d+$` 패턴을 제거하려 하지만, 실제 Ingest에서는 `source_id::ctx::{hash}` 형태로 suffix를 붙이므로 이 정규식 자체가 실효가 없는 상태다.

**수정 방향**

- fusion 또는 ranking 단계에서 **같은 사건 ID를 공유하는 청크를 1개로 제한**하는 로직을 추가한다. `source_id`에서 `case::{type}::{id}` prefix를 추출하면 같은 사건에서 온 청크임을 식별할 수 있다.
- 또는 RRF 이후 후처리 단계에서 이미 선택된 문서와 **텍스트 유사도가 일정 임계값(예: 0.8) 이상인 문서를 제외**하는 diversity filter를 추가한다. 단, 이 경우 매 문서 비교 비용이 발생하므로 후보 수가 적은 단계(top_k 이후)에 적용해야 한다.
- `normalize_source_id()`의 정규식을 실제 Ingest suffix 패턴(`::ctx::[a-f0-9]+$`)에 맞게 수정한다.

---

### 원인 3. related_law_names가 넓게 부여되어 법령 필터를 무력화한다

**코드 확인**

`retrieval/opensearch.py:71-81`

```python
if law_names:
    filters.append({
        "bool": {
            "should": [
                {"terms": {"law_name": law_names}},
                {"terms": {"root_law_name": law_names}},
                {"terms": {"related_law_name": law_names}},
                {"terms": {"related_law_names": law_names}},
            ],
            "minimum_should_match": 1,
        }
    })
```

`filter` 절 안에 위치하므로 OpenSearch에서는 hard filter로 동작한다. 그러나 `related_law_names` 하나만 일치해도 통과하는 구조라, 이번 케이스처럼 실질 쟁점은 공무원연금법이지만 `related_law_names`에 근로자퇴직급여 보장법이 포함된 문서는 필터를 그대로 통과한다.

이는 Ingest 단계에서 `related_law_names`를 넓게 부여한 것이 원인이지만, retrieval 단계에서도 보완할 수 있다.

**수정 방향**

- **단기(retrieval 보정):** `law_name`과 `root_law_name` 매칭에 가중치를 높이고, `related_law_names` 매칭만으로 통과한 문서는 score를 낮추는 방식으로 ranking에서 후순위로 밀어낸다.
- **장기(Ingest 협의):** `related_law_names` 부여 기준을 좁혀, 문서의 주된 법령(`root_law_name`)과 직접 관련된 법령만 포함하도록 메타데이터 생성 규칙을 수정한다. 이는 데이터 적재 담당자와 협의가 필요하다.

---

### 원인 4. ranking 단계에 다양성 제어가 없다

**코드 확인**

`retrieval/ranking.py:56-79` — `apply_law_boost()`

```python
def apply_law_boost(rows, *, question, enabled, law_boost_score):
    if not enabled or not rows or not is_normative_query(question):
        return rows
    for row in rows:
        if str(row.get("doc_type", "")) == "law":
            score += law_boost_score
```

`retrieval/ranking.py:112-175` — `select_rows_with_law_policy()`

law 문서 최소 개수 보강과 점수 정렬만 수행한다. 유사 청크가 이미 상위권에 여러 개 있어도 이를 감지하거나 제한하는 로직이 없다.

`generation/pipeline.py:298-315` — RRF 이후 최종 선택

BM25에서 유사 청크 3개가 rank 1·2·3으로 들어오면, RRF 점수 그대로 최종 Top-5에 남는다.

**수정 방향**

`select_rows_with_law_policy()` 이후 또는 내부에 아래 로직을 추가한다.

- **같은 사건 ID에서 온 청크를 최대 N개(예: 1개)로 제한:** `source_id`에서 사건 식별자 prefix를 추출해 동일 사건의 청크가 중복 선택되지 않도록 한다.
- **선택 기준:** 동일 사건의 여러 청크 중 score가 가장 높은 것만 남긴다.

---

## 3. 수정 범위 요약

| 원인 | 수정 위치 | 수정 내용 | 협의 필요 |
|------|-----------|-----------|-----------|
| BM25 광범위 매칭 | `opensearch.py:63-65`, `:103` | `operator: "and"` 또는 `minimum_should_match` 강화, `fetch_multiplier` 축소 | 불필요 |
| near-duplicate dedup 부재 | `fusion.py:23-34`, `common.py:276` | 사건 ID prefix 기준 청크 수 제한, suffix 정규식 수정 | 불필요 |
| 법령 필터 무력화 | `opensearch.py:71-81` | related_law_names 매칭 문서 ranking 하향 | Ingest 협의 병행 |
| ranking 다양성 부재 | `ranking.py:112-175` | 동일 사건 청크 수 제한 후처리 추가 | 불필요 |

---

## 4. 결론

보고서에서 지목한 4가지 원인은 모두 코드 수준에서 확인되었으며, 이 중 **BM25 매칭 강화**, **near-duplicate 제한**, **ranking 다양성 추가**는 retrieval/fusion/ranking 내부 수정만으로 즉시 조치 가능합니다.

**법령 필터 무력화**는 retrieval 단계 보정과 Ingest 메타데이터 기준 수정을 병행해야 근본적으로 해결됩니다.

이번 케이스는 단발적 예외가 아니라 BM25 특성과 메타데이터 설계가 맞물린 구조적 문제로, 동일 패턴이 다른 질의에서도 반복될 수 있습니다.
