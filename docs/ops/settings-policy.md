# 설정 정책

## 저장 방식

- 저장소: 브라우저 `localStorage`, 키 `"legal-ai-settings"`
- 포맷: JSON 직렬화
- 함수:
  - `loadSettings()` — 로드 + 유효하지 않은 값 자동 보정 → `Settings` 반환
  - `saveSettings(settings)` — 저장 + `las_settings_changed` 커스텀 이벤트 발화
  - `useSettings()` — `storage`(다른 탭) / `las_settings_changed`(같은 탭) 구독 → 저장 즉시 반영

## 설정 항목

| 키 | 타입 | 기본값 | 유효값 | 연동 |
|---|---|---|---|---|
| `model` | string | `"gemini"` | — | 현재 미사용 (백엔드 고정) |
| `topK` | number | `5` | `5` / `8` / `12` | API `top_k` 파라미터 |
| `answerDetail` | string | `"normal"` | `"brief"` / `"normal"` / `"detailed"` | API `answer_detail` 파라미터 |
| `showCitations` | boolean | `true` | — | 근거 조문 UI 표시 여부 |
| `showLawGraph` | boolean | `true` | — | 현재 미사용 (탭으로 대체) |
| `showFollowUpQuestions` | boolean | `true` | — | 추천 질문 칩 표시 여부 |

## 초기값 정책

- localStorage에 저장된 값이 없으면 `defaultSettings` 사용
- 저장된 값이 있으면 `defaultSettings`에 병합 (새 키 누락 보완)
- `topK` / `answerDetail`은 유효값 목록 외의 값이면 기본값으로 자동 보정
  - 보정 시점: `loadSettings()` 호출 시마다 (Settings 화면 진입, useSettings 훅 마운트)

## 백엔드 연동

- **`topK`** → `POST /api/v1/qa/ask/stream` 요청의 `top_k` 필드
  - 파이프라인 내 `_retrieve()` 의 `effective_top_k`로 적용 (없으면 config 기본값 사용)
  - 검색 후보 수(`candidate_k`)는 config 고정값 유지, `top_k`만 최종 선택 수에 영향
- **`answerDetail`** → 요청의 `answer_detail` 필드
  - `build_system_prompt(answer_detail)` 을 통해 시스템 프롬프트 내 `{detail_instruction}` 치환
  - `brief`: 3~5문장 요약
  - `normal`: 기본 서술형
  - `detailed`: 구조화 포맷 (배경 / 핵심 내용 / 유의사항)

## 프론트엔드 전용 설정

- **`showCitations`**: `AnswerCard`에서 근거 조문 블록 렌더링 여부 제어. 기본 3개 표시, 초과분은 `+N개 더 보기`.
- **`showFollowUpQuestions`**: 초기 화면 추천 칩 및 대화 중 하단 칩 모두 제어.
- **`showLawGraph`**: 현재 메인 화면이 탭(관련 법령 / 법령 그래프) 구조로 전환되어 미사용.
