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
        '{"law_names": ["하도급거래 공정화에 관한 법률"], "suggested_laws": [], "intent": "normative", "is_legal": true, "normalized_query": "하도급대금 지급기한 위반 제재", "hypothetical_doc": "원사업자가 하도급대금을 목적물 수령일부터 60일 이내에 지급하지 아니한 경우 지연이자를 지급하여야 한다."}',
    ),
    # ── normative: 법령명 미명시 + 단일 법령 추론 가능 → suggested_laws 포함 ──
    (
        "연장근로 허용 한도가 어떻게 되나요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "연장근로 허용 한도", "hypothetical_doc": "사용자는 근로자와 합의하면 1주 간에 12시간을 한도로 연장근로를 시킬 수 있다."}',
    ),
    (
        "직원 해고 시 사전 통보 기간은 어떻게 되나요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "해고 사전 통보 기간", "hypothetical_doc": "사용자는 근로자를 해고하려면 적어도 30일 전에 예고하여야 하고, 30일 전에 예고하지 아니한 경우에는 30일분 이상의 통상임금을 지급하여야 한다."}',
    ),
    # ── 구어체 정규화 + suggested_laws ───────────────────────────────────────
    (
        "월급 안주면 어떻게 해",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "임금 미지급 시 제재 및 구제", "hypothetical_doc": "임금은 통화로 직접 근로자에게 그 전액을 매월 1회 이상 일정한 날짜를 정하여 지급하여야 한다."}',
    ),
    (
        "근로기쥰법 연차",
        '{"law_names": ["근로기준법"], "suggested_laws": [], "intent": "normative", "is_legal": true, "normalized_query": "근로기준법 연차 유급휴가", "hypothetical_doc": "사용자는 1년간 80퍼센트 이상 출근한 근로자에게 15일의 유급휴가를 주어야 한다."}',
    ),
    # ── 다수 법령 가능 → suggested_laws [] ───────────────────────────────────
    (
        "하도급 현장 근로자 임금 체불",
        '{"law_names": [], "suggested_laws": [], "intent": "normative", "is_legal": true, "normalized_query": "하도급 현장 근로자 임금 체불 구제", "hypothetical_doc": "도급사업의 사업주는 하수급인이 사용한 근로자에게 임금을 지급하지 못한 경우 그 하수급인과 연대하여 책임을 진다."}',
    ),
    # ── normative: 벌금·처벌 여부 질문 → 의무 조문 형태 우선 ──────────────
    (
        "근로계약서 안 쓰면 벌금 있나요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "근로계약서 미작성 제재", "hypothetical_doc": "사용자는 근로계약 체결 시 임금, 소정근로시간 등 근로조건을 서면으로 명시하여 근로자에게 교부하여야 한다."}',
    ),
    # ── normative: 처벌 수위 자체를 묻는 질문 → 벌칙 조문 형태 ──────────────
    (
        "근로계약서 미작성 벌금이 얼마야",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "근로계약서 미작성 벌금", "hypothetical_doc": "근로계약을 서면으로 체결하지 아니한 자는 500만원 이하의 벌금에 처한다."}',
    ),
    # ── hypothetical_doc 빈 문자열 반환 케이스 (산입 범위 등 세부 규정은 구체적 조문 작성 불가) ──
    (
        "최저임금 계산할 때 식대나 교통비도 포함되나요",
        '{"law_names": ["최저임금법"], "suggested_laws": [], "intent": "normative", "is_legal": true, "normalized_query": "최저임금 산입 범위 식대 교통비", "hypothetical_doc": ""}',
    ),
    # ── case_law ─────────────────────────────────────────────────────────────
    (
        "프리랜서로 계약한 인력이 근로자로 인정될 수 있나요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "case_law", "is_legal": true, "normalized_query": "프리랜서 근로자성 인정 여부", "hypothetical_doc": ""}',
    ),
    # ── mixed ────────────────────────────────────────────────────────────────
    (
        "근로기준법상 연장근로 수당 관련 판례가 있나요",
        '{"law_names": ["근로기준법"], "suggested_laws": [], "intent": "mixed", "is_legal": true, "normalized_query": "연장근로 수당 판례", "hypothetical_doc": ""}',
    ),
    # ── 후속 질문 ─────────────────────────────────────────────────────────────
    (
        "그럼 야간근로는요",
        '{"law_names": [], "suggested_laws": ["근로기준법"], "intent": "normative", "is_legal": true, "normalized_query": "야간근로 수당 지급 기준", "hypothetical_doc": "사용자는 야간근로(오후 10시부터 오전 6시까지)에 대하여 통상임금의 100분의 50 이상을 가산하여 지급하여야 한다."}',
    ),
    (
        "수습직원 3개월 후 정규직 전환 안 하려면",
        '{"law_names": [], "suggested_laws": ["기간제 및 단시간근로자 보호 등에 관한 법률"], "intent": "normative", "is_legal": true, "normalized_query": "수습직원 정규직 전환 거부 요건", "hypothetical_doc": "사용자는 2년을 초과하여 기간제근로자를 사용하는 경우 그 기간제근로자는 기간의 정함이 없는 근로계약을 체결한 근로자로 본다."}',
    ),
    # ── 무관 질문 ─────────────────────────────────────────────────────────────
    (
        "오늘 날씨 어때요",
        '{"law_names": [], "suggested_laws": [], "intent": null, "is_legal": false, "normalized_query": "", "hypothetical_doc": ""}',
    ),
    (
        "오늘 점심 뭐 먹을까요",
        '{"law_names": [], "suggested_laws": [], "intent": null, "is_legal": false, "normalized_query": "", "hypothetical_doc": ""}',
    ),
]
