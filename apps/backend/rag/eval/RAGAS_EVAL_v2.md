# RAG 파이프라인 평가 v2

> **이전 보고서:** `RAGAS_EVAL.md` (탐색 단계, 1~10차 측정, Gemini 기반, 2026-03-26 ~ 2026-04-16)
> **이 보고서:** eval_set 정비 및 eval 스크립트 버그 수정 이후 OpenAI 기반 신규 baseline부터 측정

---

## 1. v1 대비 변경사항

| 항목 | v1 (RAGAS_EVAL.md) | v2 (이 파일) |
|---|---|---|
| eval_set | 43건 (산재법 포함) | **40건** (산업재해보상보험법 3건 제거) |
| 평가 LLM | Gemini | **OpenAI** (Gemini API 차단) |
| `suggested_laws` 적용 | ❌ (버그) | **✅** |
| `search_query` 전달 | ❌ (버그) | **✅** |
| `hypothetical_doc` 전달 | ❌ (버그) | **✅** |
| law_names.py | 산재법 포함 | **산재법 제거** |

평가 LLM이 달라졌으므로 v1 수치와 직접 비교는 불가. **이 파일의 1차 측정이 새 baseline.**

---

## 2. eval_set 구성

`data/staging/eval_set.csv` — 총 **40건**, 3가지 intent

| intent | 설명 | 건수 |
|---|---|---|
| `normative` | 요건·의무·기준 질의 | 22건 |
| `case_law` | 판례·행정심판례 질의 | 11건 |
| `mixed` | 법령 + 판례 복합 질의 | 8건 |

커버리지 법령 (9종): 근로기준법, 기간제법, 파견근로자법, 최저임금법, 남녀고용평등법, 퇴직급여법, 하도급법, 건설산업기본법

---

## 3. 평가 메트릭

| 메트릭 | 의미 | 비고 |
|---|---|---|
| `answer_relevancy` | 답변이 질문에 관련 있는가 | LLM 판단, 노이즈 있음 |
| `context_precision` | 관련 문서가 상위에 랭크되는가 | LLM 판단, 노이즈 있음 |
| `faithfulness` | 답변이 컨텍스트에 근거하는가 | answer_relevancy < 0.6 건만 선택적 측정 |
| `law_hit` | gold_law 문서가 retrieved_docs에 포함되는가 | 결정론적, LLM 판단 없음 |

---

## 4. 측정 결과

### 1차 측정 (baseline, 2026-04-30)

> eval_set 정비 + eval 스크립트 버그 수정 후 첫 측정. **이 수치를 v2 baseline으로 삼는다.**
> 파일: `eval_results/eval_20260430_170126.csv`

| 메트릭 | 전체 평균 |
|---|---|
| answer_relevancy | **0.778** (n=39) |
| context_precision | **0.901** (n=39) |
| faithfulness | **0.500** (n=3, 저점수 대상) |
| law_hit | **0.656** (n=32) |

| intent | n | answer_relevancy | context_precision |
|---|---|---|---|
| normative | 20 | 0.782 | 0.869 |
| case_law | 11 | 0.765 | 0.887 |
| mixed | 8 | 0.785 | 1.000 |

- `law_context_status`: ok 26건, case_only 10건, missing 3건, irrelevant 1건
- `answer_relevancy` 0.0 저점수 3건
  - case_law: 고용보험료 추가 부과 처분을 받았을 때 이의를 제기할 수 있나요
  - normative: 출산전후휴가 기간과 급여 지원 기준이 어떻게 되나요
  - normative: 육아휴직 신청을 거부하면 어떤 제재를 받나요

**이슈 분석**

| 쿼리 | 원인 | 비고 |
|---|---|---|
| 고용보험료 추가 부과 | 고용보험법은 커버리지 외. 파서가 퇴직급여법으로 잘못 라우팅, 무관한 답변 생성 | eval_set 재검토 필요 |
| 출산전후휴가 | 파서가 남녀고용평등법 추출 → hard filter 적용 → 근로기준법 제74조 retrieval 차단 → missing | 파서 정확도 or 슬롯 전략 문제 |
| 육아휴직 거부 제재 | 동일 패턴 (남녀고용평등법 hard filter → missing). 일관된 구조적 문제 | |

- **missing 3건 모두 남녀고용평등법 관련** — 파서가 해당 법령을 추출하면 근로기준법 조문이 차단되는 패턴. 남녀고용평등법 관련 질의의 핵심 조문 상당수가 근로기준법에 있기 때문
- **law_hit 0.656** — v1 10차(0.600) 대비 상승. eval 스크립트 버그 수정(suggested_laws 적용) 효과

---

## 5. 이슈 트래킹

### 진행 중

| 이슈 | 내용 | 우선순위 |
|---|---|---|
| 남녀고용평등법 missing | 파서 법령 추출 → hard filter로 근로기준법 차단. normative 슬롯 전략과 충돌 | 높음 |
| 고용보험료 쿼리 | 커버리지 외 법령 질의. eval_set에서 제거 또는 gold_law 수정 필요 | 낮음 |
| mixed context_precision | v1부터 지속된 과제. 법령+판례 복합 질의 컨텍스트 비율 조정 | 중간 |

### 완료 (v1에서 이관)

| 항목 | 결과 |
|---|---|
| normative missing 해소 | 슬롯 기반 검색으로 missing 0건 달성 (v1 9차) |
| case_law 필터 전략 | intent 기반 hard filter 해제로 rel 0.699 → 0.954 (v1 7차) |
| eval 스크립트 버그 수정 | suggested_laws, search_query, hypothetical_doc 미전달 3건 수정 |
| eval_set 정비 | 산재법 3건 제거, law_names.py 동기화 |
