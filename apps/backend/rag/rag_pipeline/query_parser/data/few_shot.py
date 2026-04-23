"""Query Parser few-shot 예시.

각 예시는 (query, expected_output) 쌍으로 구성된다.
- normative  : 법령 조문 기반 답변이 필요한 질문
- case_law   : 판례/해석례 기반 답변이 필요한 질문
- mixed      : 조문 + 판례 모두 필요한 질문
- irrelevant : 법률과 무관한 질문 (is_legal=false)
"""

from __future__ import annotations

# (query, JSON 출력 문자열) 형태로 정의
# 출처: eval_set.csv 선별 + 무관 질문 직접 작성
FEW_SHOT_EXAMPLES: list[tuple[str, str]] = [
    # ── normative: 법령명 명시 → suggested_laws 불필요 ───────────────────────
    (
        "하도급거래 공정화에 관한 법률상 대금 지급 기한을 어기면 어떤 불이익이 있나요",
        '{"law_names": ["하도급거래 공정화에 관한 법률"], "suggested_laws": [], "intent": "normative", "is_legal": true, "normalized_query": "하도급대금 지급기한 위반 제재"}',
    ),
    # ── normative: 법령명 미명시 + 단일 법령 추론 가능 → suggested_laws 포함 ──
    (
        "연장근로 허용 한도가 어떻게 되나요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "연장근로 허용 한도"}',
    ),
    (
        "직원 해고 시 사전 통보 기간은 어떻게 되나요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "해고 사전 통보 기간"}',
    ),
    # ── 구어체 정규화 + suggested_laws ───────────────────────────────────────
    (
        "월급 안주면 어떻게 해",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "임금 미지급 시 제재 및 구제"}',
    ),
    (
        "근로기쥰법 연차",
        '{"law_names": ["근로기준법"], "suggested_laws": [], "intent": "normative", "is_legal": true, "normalized_query": "근로기준법 연차 유급휴가"}',
    ),
    # ── 다수 법령 가능 → suggested_laws [] ───────────────────────────────────
    (
        "하도급 현장 근로자 임금 체불",
        '{"law_names": [], "suggested_laws": [], "intent": "normative", "is_legal": true, "normalized_query": "하도급 현장 근로자 임금 체불 구제"}',
    ),
    # ── case_law ─────────────────────────────────────────────────────────────
    (
        "프리랜서로 계약한 인력이 근로자로 인정될 수 있나요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "case_law", "is_legal": true, "normalized_query": "프리랜서 근로자성 인정 여부"}',
    ),
    # ── mixed ────────────────────────────────────────────────────────────────
    (
        "근로기준법상 연장근로 수당 관련 판례가 있나요",
        '{"law_names": ["근로기준법"], "suggested_laws": [], "intent": "mixed", "is_legal": true, "normalized_query": "연장근로 수당 판례"}',
    ),
    # ── 후속 질문 ─────────────────────────────────────────────────────────────
    (
        "그럼 야간근로는요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "야간근로 수당 지급 기준"}',
    ),
    (
        "수습직원 3개월 후 정규직 전환 안 하려면",
        '{"law_names": [], "suggested_laws": ["기간제 및 단시간근로자 보호 등에 관한 법률"], "intent": "normative", "is_legal": true, "normalized_query": "수습직원 정규직 전환 거부 요건"}',
    ),
    # ── 무관 질문 ─────────────────────────────────────────────────────────────
    (
        "오늘 날씨 어때요",
        '{"law_names": [], "suggested_laws": [], "intent": null, "is_legal": false, "normalized_query": ""}',
    ),
    (
        "오늘 점심 뭐 먹을까요",
        '{"law_names": [], "suggested_laws": [], "intent": null, "is_legal": false, "normalized_query": ""}',
    ),
]
