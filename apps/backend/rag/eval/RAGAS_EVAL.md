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
| `faithfulness` | 답변이 컨텍스트에 근거하는가 | 생성 단계 hallucination |
| `answer_relevancy` | 답변이 질문에 관련 있는가 | 프롬프트·생성 품질 문제 |
| `context_precision` | 관련 문서가 상위에 랭크되는가 | retrieval 순위 문제 |

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

### 4-4. 종합 해석

- **normative `context_precision`이 일관되게 최저** (0.41~0.43) — 사용자 표현과 법령 원문 간 어휘 불일치가 핵심 원인으로 추정
- LLM 판단 기반 메트릭 특성상 실행마다 노이즈 존재. 단일 수치보다 추세로 판단 필요
- **다음 개선 타겟: normative 유형의 retrieval 품질** (동의어 사전, query 확장)

---

## 5. 앞으로 기대되는 도출

### 단기 ✅ 완료

- **intent별 점수 비교** → normative의 context_precision이 일관되게 최저임을 확인
- **law_context_status 분포** → 현재 전 건 `ok` (missing 문제는 retrieval 순위 문제로 나타남)
- **저점수 쿼리 목록** → 0점 6건 확인 및 원인 파악

### 중기 (개선 적용 후 비교)

| 개선 방향 | 기대 효과 측정 방법 |
|---|---|
| 동의어 사전 (기재사항 → 명시사항 등) | context_precision 변화 |
| normative 키워드 확장 | law_context_status missing 감소 |
| HyDE 도입 | context_precision + answer_relevancy 변화 |

동일 eval_set으로 반복 측정하여 **개선 전후를 수치로 비교**할 수 있게 됩니다.

### 장기

- CI 파이프라인 연동 → 배포 전 자동 회귀 테스트
- eval_set에 `ground_truth` 컬럼 추가 → `context_recall`, `answer_correctness` 측정 가능
