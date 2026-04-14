# RAG 파이프라인 평가 도입 배경 및 설계

## 1. 문제 인식

LAS 시스템은 법률 전문가가 아닌 **기업 법무 담당자**를 주요 사용자로 합니다.
이로 인해 다음과 같은 품질 문제가 체감 수준에서 발견되었습니다.

- `"근로계약서 작성 시 필수 기재사항은?"` 처럼 명확한 질문에도 `law_context_status: missing` 이 반환되며 근거 없는 답변 생성
- 사용자가 법령명을 직접 입력하지 않아 필터가 동작하지 않는 경우가 빈번
- eval_set 하단의 행정심판례(decc), 법령해석례(expc), 연관관계(relation) 유형 질의에서 답변 품질 급격히 저하

근본 원인으로 **어휘 불일치(vocabulary mismatch)** 가 의심되었습니다.
예: 사용자 표현 "기재사항" ↔ 법령 원문 "명시하여야 할 사항"

query parser, 동의어 사전, HyDE 등 여러 개선 방향이 논의되었으나, **어디서 무엇이 문제인지 데이터 없이는 방향을 정할 수 없다**는 판단 하에 평가 체계 구축을 먼저 진행했습니다.

---

## 2. RAGAS를 선택한 이유

| 고려 사항 | 판단 |
|---|---|
| ground_truth(정답 텍스트) 미보유 | RAGAS는 reference 없이도 3개 핵심 메트릭 측정 가능 |
| RAG 파이프라인 특화 | retrieval + generation 각 단계를 분리 측정 |
| 기존 인프라 재활용 | 평가 LLM으로 파이프라인과 동일한 Gemini 사용 가능 |
| 빠른 도입 | eval_set CSV만 있으면 스크립트 한 번으로 측정 |

---

## 3. 설계

### 3-1. eval_set (`data/staging/eval_set.csv`)

총 28개 쿼리, 3가지 intent로 구성:

| intent | 설명 | 비중 |
|---|---|---|
| `normative` | 요건·의무·기준 질의 | 11개 |
| `case_law` | 판례·행정심판례 질의 | 13개 |
| `mixed` | 법령 + 판례 복합 질의 | 4개 |

각 행에 `gold_law`, `gold_article`, `expected_doc_type` 포함 (향후 ground_truth 추가 시 context_recall 측정 가능).

### 3-2. 평가 메트릭

ground_truth 없이 측정 가능한 3개 메트릭 사용:

| 메트릭 | 의미 | 낮으면 의심되는 원인 |
|---|---|---|
| `answer_relevancy` | 답변이 질문에 관련 있는가 | 프롬프트·생성 품질 문제 |
| `context_precision` | 관련 문서가 상위에 랭크되는가 | retrieval 순위 문제 |
| ~~`faithfulness`~~ | ~~답변이 컨텍스트에 근거하는가~~ | 비용/시간 문제로 현재 미측정 |

### 3-3. 실행 구조 (`eval/run_eval.py`)

```
eval_set.csv
    ↓
[Step 1] RagPipeline.run() × N개
    ↓ question / answer / retrieved_contexts / law_context_status
[Step 2] RAGAS batch_score()
    ↓ faithfulness / answer_relevancy / context_precision
[Output] data/staging/eval_results/eval_YYYYMMDD_HHMMSS.csv
         + 터미널 intent별 요약
```

- Gemini 무료 티어 대응: `batch_size=2`, 배치 간 65초 대기
- `DiskCacheBackend`: 동일 입력 재평가 시 API 호출 없음
- `--limit N` 옵션으로 빠른 부분 측정 지원

---

## 4. 측정 결과

> `faithfulness`는 비용/시간 문제로 현재 측정에서 제외. 추후 `ragas.metrics.collections.Faithfulness`로 추가 가능.

### 4-1. 초기 측정 (normative 5개, 2026-03-26)

| 메트릭 | 점수 |
|---|---|
| answer_relevancy | **0.693** |
| context_precision | **0.612** |

- 상대적으로 쉬운 normative 유형만의 결과. 전체 포함 시 수치 하락 예상.

### 4-2. 전체 28개 baseline (2026-03-27)

| 메트릭 | 전체 평균 |
|---|---|
| answer_relevancy | **0.662** |
| context_precision | **0.492** |

| intent | n | answer_relevancy | context_precision |
|---|---|---|---|
| normative | 10 | 0.716 | 0.410 |
| case_law | 12 | 0.677 | 0.567 |
| mixed | 6 | 0.542 | 0.476 |

- `law_context_status`: 28건 모두 `ok`

### 4-3. 2차 측정 (2026-03-30)

| 메트릭 | 전체 평균 |
|---|---|
| answer_relevancy | **0.686** |
| context_precision | **0.483** |

| intent | n | answer_relevancy | context_precision |
|---|---|---|---|
| normative | 10 | 0.613 | 0.432 |
| case_law | 12 | 0.735 | 0.541 |
| mixed | 6 | 0.711 | 0.454 |

- `law_context_status`: 28건 모두 `ok`
- `answer_relevancy` 0.0 저점수 6건: normative 3건, case_law 2건, mixed 1건
  - 해당 쿼리 모두 "컨텍스트에 정보가 부족합니다" 형태의 답변 → retrieval 자체 실패
  - 예: 연장근로 허용 한도, 근로계약서 미작성, 하도급 대금 지급 기한

### 4-4. 3차 측정 (2026-03-30, GCP OpenSearch 연동 후)

> GCP OpenSearch 인덱스 구조 정비 후 측정 (`search_text` 필드 전환, 인덱스 3개 분리)

| 메트릭 | 전체 평균 |
|---|---|
| answer_relevancy | **0.703** |
| context_precision | **0.526** |

| intent | n | answer_relevancy | context_precision |
|---|---|---|---|
| normative | 10 | 0.668 | 0.445 |
| case_law | 12 | 0.747 | 0.634 |
| mixed | 6 | 0.674 | 0.447 |

- `law_context_status`: 28건 모두 `ok`
- `answer_relevancy` 0.0 저점수 5건 (이전 6건 → 1건 감소)
  - 예: 연장근로 허용 한도, 근로계약서 미작성, 도급계약 근로자 인정, 연장근로 수당 산정, 도산 사실 인정 거부
- **context_precision 0.483 → 0.526** — `search_text` 필드 전환 및 인덱스 구조 정비 효과. 특히 `case_law` prec 0.541 → 0.634 큰 폭 개선

### 4-5. 4차 측정 (2026-03-31, OpenAI 임베딩 적용 후 baseline)

> OpenAI `text-embedding-3-large` (1024 dim) 전환 후 측정. Query Parser 미적용 baseline.

| 메트릭 | 전체 평균 |
|---|---|
| answer_relevancy | **0.756** |
| context_precision | **0.692** |

| intent | n | answer_relevancy | context_precision |
|---|---|---|---|
| normative | 10 | 0.866 | 0.637 |
| case_law | 12 | 0.684 | 0.731 |
| mixed | 6 | 0.717 | 0.705 |

- `law_context_status`: ok 26건, supplemented 2건
- `answer_relevancy` 0.0 저점수 4건 (이전 5건 → 1건 감소)
  - mixed: 직원이 부당해고를 주장할 경우 회사가 어떻게 대응해야 하나요
  - case_law: 도급 계약 인력에게 업무 지시를 하면 근로자로 볼 수 있나요
  - case_law: 폐업 후 도산 사실 인정이 거부된 경우 어떻게 대응해야 하나요
  - case_law: 근로기준법 위반으로 제재받은 사례가 있나요
- **전 구간에서 큰 폭 개선** — answer_relevancy 0.703 → 0.756, context_precision 0.526 → 0.692
- 특히 normative context_precision이 0.445 → 0.637로 가장 크게 향상 (어휘 불일치 문제 완화 효과)

### 4-6. 5차 측정 (2026-03-31, eval_set v2 기준 새 baseline)

> **eval_set 전면 개편** (28 → 43건): gold_article 오류 수정, 법령별 커버리지 보강(기간제·파견·퇴직급여·남녀고용평등·건설산업기본법·산재보험법), case_law에 gold_issue_keyword 추가, Query Parser 미적용 baseline.
> 이전 측정(4-1~4-5)과 eval_set이 달라 수치 직접 비교는 불가. 이 결과를 v2 eval_set의 기준값으로 삼는다.

| 메트릭 | 전체 평균 |
|---|---|
| answer_relevancy | **0.836** |
| context_precision | **0.740** |

| intent | n | answer_relevancy | context_precision |
|---|---|---|---|
| normative | 22 | 0.902 | 0.755 |
| case_law | 13 | 0.699 | 0.703 |
| mixed | 8 | 0.877 | 0.758 |

- `law_context_status`: ok 41건, supplemented 2건
- `answer_relevancy` 0.0 저점수 3건
  - case_law: 도급계약으로 체결한 외주 인력이 근로자로 인정될 가능성이 있나요
  - case_law: 폐업 후 도산 사실 인정이 거부된 경우 어떻게 대응해야 하나요
  - case_law: 근로기준법 위반으로 제재받은 사례가 있나요
- normative가 이전 대비 높은 수치 — gold_article 오류 수정 및 평가 대상 확대 효과로 보임
- 저점수 3건 모두 case_law 중 `prec` / `relation` 타입 → corpus에 판례 문서 자체가 부족하거나 retrieval이 법령 문서로 치우치는 현상 의심

### 4-7. 6차 측정 (2026-03-31, Query Parser 적용, intent별 필터 최적화 전)

> Query Parser 적용 (`--use-parser`). intent별 필터 전략 미적용 상태 — `case_law` 질의에도 law_names hard filter + `min_law_contexts` 강제 보강이 동작하는 버전.
> **v2 eval_set 기준 (4-6 baseline 비교 가능).**

| 메트릭 | 전체 평균 |
|---|---|
| answer_relevancy | **0.846** (n=39) |
| context_precision | **0.718** (n=39) |

| intent | n | answer_relevancy | context_precision |
|---|---|---|---|
| normative | 19 | 0.898 | 0.698 |
| case_law | 12 | 0.755 | 0.715 |
| mixed | 8 | 0.860 | 0.767 |

- `law_context_status`: ok 37건, missing 4건, supplemented 2건
- `answer_relevancy` 0.0 저점수 2건
  - case_law: 폐업 후 도산 사실 인정이 거부된 경우 어떻게 대응해야 하나요
  - case_law: 기간제 근로자 계약 만료 후 묵시적 갱신이 인정될 수 있나요
- **case_law rel 0.699 → 0.755** (+0.056) — 파서가 법령 컨텍스트 힌트 제공 효과
- **normative prec 0.755 → 0.698** (-0.057), **missing 4건 발생** — law_names hard filter 과적용으로 인한 retrieval 실패
- n이 43→39로 감소 (missing 4건 = RAGAS 평가 제외)

### 4-8. 7차 측정 (2026-04-09, intent 기반 필터 전략 적용 + RAGAS 강화)

> intent 기반 법령 필터 전략 적용 (`case_law` 질의는 law_names hard filter 미적용, `case_only` status 신규 도입) + RAGAS 강화 (평가 LLM gemini-2.5-flash-lite, faithfulness 메트릭, Langfuse score push). Query Parser 기본 적용.
> **v2 eval_set 기준 (4-6 baseline, 4-7 비교 가능).**

| 메트릭 | 전체 평균 |
|---|---|
| answer_relevancy | **0.898** (n=40) |
| context_precision | **0.651** (n=40) |
| law_hit | **0.571** (n=35, 신규 지표) |

| intent | n | answer_relevancy | context_precision |
|---|---|---|---|
| normative | 20 | 0.868 | 0.640 |
| case_law | 12 | 0.954 | 0.722 |
| mixed | 8 | 0.890 | 0.574 |

- `law_context_status`: ok 23건, case_only 14건, missing 4건, irrelevant 1건, supplemented 1건
- `answer_relevancy` 0.0 저점수 1건
  - normative: 육아휴직 신청을 거부하면 어떤 제재를 받나요
- faithfulness: 0건 측정 (answer_relevancy ≥ 0.6 전 건 해당). 0.0 점 1건은 `0.0 or 1.0 = 1.0` 버그로 대상 제외됨 → 버그 수정 완료, 다음 실행부터 반영

**4-7 대비 변화 분석**

| intent | rel 변화 | prec 변화 |
|---|---|---|
| case_law | 0.755 → **0.954** (+0.199) ↑ | 0.715 → **0.722** (+0.007) → |
| normative | 0.898 → **0.868** (-0.030) ↓ | 0.698 → **0.640** (-0.058) ↓ |
| mixed | 0.860 → **0.890** (+0.030) ↑ | 0.767 → **0.574** (-0.193) ↓ |

- **case_law rel +0.199** — intent 기반 필터로 law_names hard filter 해제 효과. `case_only` 14건 발생 = 판례 전용 retrieval 정상 동작
- **normative prec -0.058** — case_only 도입으로 일부 법령 컨텍스트 구성 방식 변화. 원인 추가 분석 필요
- **mixed prec -0.193** — 법령 + 판례 복합 질의에서 컨텍스트 균형이 깨진 것으로 의심. **다음 개선 타겟**
- **law_hit 0.571** — retrieval 대상 중 57%가 gold_law 문서 포함. 절반 정도는 올바른 법령 문서를 찾고 있음

### 4-9. 종합 해석

- **case_law rel 0.699 → 0.954** — intent 기반 필터 전략 적용 후 판례 질의 품질이 가장 크게 개선됨. 구조적 문제(law_names hard filter가 판례 retrieval 방해) 해소 확인
- **mixed prec 일관 하락** — 법령+판례 복합 질의에서 컨텍스트 비율 조정 전략 필요. 다음 개선 타겟
- **normative는 안정적** — OpenAI 임베딩 전환 이후 어휘 불일치 문제 완화 유지. prec 소폭 하락은 필터 전략 변경 영향으로 추정
- **law_hit은 retrieval recall 보조 지표** — LLM 판단 없는 결정론적 수치. RAGAS 메트릭과 함께 추세 모니터링
- LLM 판단 기반 메트릭 특성상 실행마다 노이즈 존재. 단일 수치보다 추세로 판단 필요

---

## 5. 앞으로 기대되는 도출

### 단기 ✅ 완료

- **intent별 점수 비교** → normative의 context_precision이 일관되게 최저임을 확인
- **law_context_status 분포** → 현재 전 건 `ok` (missing 문제는 retrieval 순위 문제로 나타남)
- **저점수 쿼리 목록** → 0점 건 확인 및 원인 파악 (어휘 불일치)
- **intent 기반 필터 전략** ✅ → case_law rel +0.199 개선 확인 (4-8)
- **RAGAS 강화** ✅ → faithfulness 메트릭, Langfuse score push, law_hit 지표 도입 (4-8)

### 중기 (개선 적용 후 비교)

| 개선 방향 | 기대 효과 측정 방법 |
|---|---|
| mixed 컨텍스트 비율 조정 | mixed context_precision 회복 여부 |
| 동의어 사전 (기재사항 → 명시사항 등) | normative context_precision 변화 |
| HyDE 도입 | context_precision + answer_relevancy 변화 |

동일 eval_set으로 반복 측정하여 **개선 전후를 수치로 비교**할 수 있게 됩니다.

### 장기

- CI 파이프라인 연동 → 배포 전 자동 회귀 테스트
- eval_set에 `ground_truth` 컬럼 추가 → `context_recall`, `answer_correctness` 측정 가능
