# 피드백 데이터 활용 가이드

## 1. 개요

사용자 피드백(👍 / 👎 + 선택적 코멘트)은 RAG 파이프라인의 품질을 지속적으로 개선하기 위한 핵심 신호다.
단순한 만족도 수집을 넘어, **retrieval 품질 진단 → 데이터셋 보강 → 모델/프롬프트 개선** 의 순환 루틴을 구성하는 것이 목표다.

---

## 2. 수집 데이터 구조

```
qa_history   : qa_id, question, answer, law_context_status, session_id, created_at
qa_sources   : qa_id, source_id, doc_type, law_name, article_no, rank, score, snippet
feedback     : qa_id, thumbs_up (bool), comment, created_at
```

분석의 핵심 조인:
```sql
SELECT h.question, h.answer, h.law_context_status,
       f.thumbs_up, f.comment,
       s.doc_type, s.law_name, s.article_no, s.rank, s.score
FROM feedback f
JOIN qa_history h ON f.qa_id = h.id
JOIN qa_sources s ON s.qa_id = h.id
ORDER BY f.created_at DESC;
```

---

## 3. 활용 방향

### 3-1. Retrieval 품질 진단 (우선순위 높음)

피드백 부정(👎) 케이스의 retrieval 로그를 분석해 **어떤 경우에 잘못된 문서가 검색되는지** 파악한다.

**추출 쿼리 — 부정 피드백 질문 목록**
```sql
SELECT h.id, h.question, h.law_context_status,
       f.comment,
       COUNT(s.id) AS source_count,
       AVG(s.score) AS avg_score
FROM feedback f
JOIN qa_history h ON f.qa_id = h.id
LEFT JOIN qa_sources s ON s.qa_id = h.id
WHERE f.thumbs_up = false
GROUP BY h.id, h.question, h.law_context_status, f.comment
ORDER BY f.created_at DESC;
```

**분석 포인트**

| 항목 | 확인 내용 |
|------|-----------|
| `law_context_status` | `missing` / `supplemented` 비율이 높으면 retrieval 자체가 실패한 케이스 |
| `avg_score` | 낮은 score임에도 상위에 노출된 문서 → 임베딩 또는 reranker 문제 |
| `rank 1` 문서의 `doc_type` | 질문 의도(법령/판례/해석례)와 불일치하는 경우 필터링 로직 점검 |
| `comment` 텍스트 | "관련 없는 법령", "오래된 판례" 등 패턴 분류 |

---

### 3-2. Hard Negative 데이터셋 구축

부정 피드백 케이스는 retrieval 모델의 **hard negative** 학습 데이터로 직접 활용할 수 있다.

```
(query, 실제 검색된 문서 = negative, 정답 문서 = positive)
```

**루틴**
1. 👎 질문 추출
2. 해당 `qa_sources`에서 상위 검색 문서 확인 (`rank 1~3`)
3. 코멘트 또는 수동 검토를 통해 정답 문서 식별
4. `(query, positive, negative)` triplet 형태로 fine-tuning 데이터셋에 추가

---

### 3-3. 프롬프트 / 생성 품질 개선

`law_context_status = ok` 임에도 👎가 나온 경우 → retrieval은 성공했으나 **생성(generation) 단계** 문제일 가능성이 높다.

```sql
SELECT h.question, h.answer, f.comment
FROM feedback f
JOIN qa_history h ON f.qa_id = h.id
WHERE f.thumbs_up = false
  AND h.law_context_status = 'ok';
```

분석 포인트:
- 답변이 너무 길거나 짧은 경우 → 프롬프트 길이/형식 조정
- 법령 인용 오류 → 컨텍스트 주입 방식 점검
- 코멘트에 "틀렸다" 류의 표현 → 사실 오류 케이스로 분류, 우선 검토

---

### 3-4. 긍정 피드백 — 정답 예시 수집

👍 케이스는 **골든 셋(golden set)** 으로 활용한다.

```sql
SELECT h.question, h.answer, h.law_context_status
FROM feedback f
JOIN qa_history h ON f.qa_id = h.id
WHERE f.thumbs_up = true
  AND h.law_context_status = 'ok';
```

- 회귀 테스트용 Q&A 쌍으로 등록
- 프롬프트 변경 시 기존 골든 셋 품질이 유지되는지 검증

---

## 4. 분석 루틴 (주기적 실행)

### 주간 루틴

```
1. 부정 피드백 건수 및 비율 집계
   - 전체 피드백 중 thumbs_up = false 비율
   - law_context_status별 부정 피드백 비율 (missing/supplemented 집중 확인)

2. 부정 피드백 질문 샘플링 (10~20건)
   - 코멘트 있는 케이스 우선
   - retrieval 결과(qa_sources) 수동 검토

3. 이슈 분류
   - [ ] Retrieval 실패 (잘못된 문서 검색)
   - [ ] 컨텍스트 부족 (관련 문서 없음)
   - [ ] 생성 오류 (문서는 맞으나 답변 품질 저하)
   - [ ] 범위 외 질문 (법률 무관 또는 지원 범위 초과)
```

### 월간 루틴

```
1. 긍정/부정 트렌드 시각화 (날짜별, 질문 유형별)
2. 누적 hard negative 데이터셋 업데이트
3. 골든 셋 보강 (신규 👍 케이스 추가)
4. 임베딩 모델 또는 reranker 재평가 (필요 시)
```

---

## 5. 향후 확장 고려사항

| 항목 | 내용 |
|------|------|
| 세션 기반 집계 | `session_id`로 묶어 대화 흐름 단위의 만족도 측정 |
| 질문 유형 태깅 | `intent` 필드(근로기준법/하도급법/판례 등) 별 피드백 분포 확인 |
| 자동 알림 | 부정 피드백 비율이 임계값(예: 30%) 초과 시 슬랙/이메일 알림 |
| A/B 테스트 | 프롬프트 또는 retrieval 설정 변경 시 피드백 비율로 효과 측정 |
