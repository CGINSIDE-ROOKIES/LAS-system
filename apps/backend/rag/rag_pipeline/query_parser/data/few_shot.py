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
    # ── normative: 법령명 명시 ────────────────────────────────────────────────
    (
        "하도급거래 공정화에 관한 법률상 대금 지급 기한을 어기면 어떤 불이익이 있나요",
        '{"law_names": ["하도급거래 공정화에 관한 법률"], "intent": "normative", "is_legal": true}',
    ),
    # ── normative: 법령명 미명시 → [] ────────────────────────────────────────
    (
        "연장근로 허용 한도가 어떻게 되나요",
        '{"law_names": [], "intent": "normative", "is_legal": true}',
    ),
    (
        "직원 해고 시 사전 통보 기간은 어떻게 되나요",
        '{"law_names": [], "intent": "normative", "is_legal": true}',
    ),
    # ── case_law ─────────────────────────────────────────────────────────────
    (
        "프리랜서로 계약한 인력이 근로자로 인정될 수 있나요",
        '{"law_names": [], "intent": "case_law", "is_legal": true}',
    ),
    # ── mixed ────────────────────────────────────────────────────────────────
    (
        "근로기준법상 연장근로 수당 관련 판례가 있나요",
        '{"law_names": ["근로기준법"], "intent": "mixed", "is_legal": true}',
    ),
    # ── 후속 질문: 이전 질문 맥락으로 법률 관련 판단 ────────────────────────────
    (
        "[이전 질문] 연장근로수당 지급 기준은 무엇인가요\n[현재 질문] 그럼 야간근로는요",
        '{"law_names": [], "article_no": "", "intent": "normative", "is_legal": true}',
    ),
    # ── 대화 중 무관 질문: 이전 질문이 법률이어도 false ──────────────────────────
    (
        "[이전 질문] 연장근로수당 지급 기준은 무엇인가요\n[현재 질문] 오늘 날씨 어때요",
        '{"law_names": [], "article_no": "", "intent": null, "is_legal": false}',
    ),
    # ── irrelevant ───────────────────────────────────────────────────────────
    (
        "오늘 점심 뭐 먹을까요",
        '{"law_names": [], "intent": null, "is_legal": false}',
    ),
]
