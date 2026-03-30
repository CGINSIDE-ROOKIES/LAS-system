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
    # ── normative ────────────────────────────────────────────────────────────
    (
        "연장근로 허용 한도가 어떻게 되나요",
        '{"law_names": ["근로기준법"], "article_no": "제53조", "intent": "normative", "is_legal": true}',
    ),
    (
        "내년도 최저임금 기준은 어떻게 결정되나요",
        '{"law_names": ["최저임금법"], "article_no": "제4조", "intent": "normative", "is_legal": true}',
    ),
    (
        "하도급 대금 지급 기한을 어기면 어떤 불이익이 있나요",
        '{"law_names": ["하도급거래 공정화에 관한 법률"], "article_no": "제13조", "intent": "normative", "is_legal": true}',
    ),
    # 약칭 포함 예시
    (
        "기간제법상 계약직 2년 초과하면 어떻게 되나요",
        '{"law_names": ["기간제 및 단시간근로자 보호 등에 관한 법률"], "article_no": "제4조", "intent": "normative", "is_legal": true}',
    ),
    # ── case_law ─────────────────────────────────────────────────────────────
    (
        "프리랜서로 계약한 인력이 근로자로 인정될 수 있나요",
        '{"law_names": [], "article_no": "", "intent": "case_law", "is_legal": true}',
    ),
    (
        "도급계약으로 체결한 외주 인력이 근로자로 인정될 가능성이 있나요",
        '{"law_names": [], "article_no": "", "intent": "case_law", "is_legal": true}',
    ),
    (
        "하도급법 위반으로 시정명령을 받은 경우 법원 판단은 어떤가요",
        '{"law_names": ["하도급거래 공정화에 관한 법률"], "article_no": "", "intent": "case_law", "is_legal": true}',
    ),
    # ── mixed ────────────────────────────────────────────────────────────────
    (
        "직원이 부당해고를 주장할 경우 회사가 어떻게 대응해야 하나요",
        '{"law_names": ["근로기준법"], "article_no": "제26조", "intent": "mixed", "is_legal": true}',
    ),
    (
        "연장근로 수당 관련 분쟁 판례나 해석 사례가 있나요",
        '{"law_names": ["근로기준법"], "article_no": "제53조", "intent": "mixed", "is_legal": true}',
    ),
    # ── irrelevant ───────────────────────────────────────────────────────────
    (
        "오늘 점심 뭐 먹을까요",
        '{"law_names": [], "article_no": "", "intent": null, "is_legal": false}',
    ),
    (
        "파이썬으로 웹 크롤링하는 방법 알려줘",
        '{"law_names": [], "article_no": "", "intent": null, "is_legal": false}',
    ),
    (
        "요즘 주식 투자 어떻게 해야 하나요",
        '{"law_names": [], "article_no": "", "intent": null, "is_legal": false}',
    ),
    (
        "안녕하세요 무엇을 도와드릴까요",
        '{"law_names": [], "article_no": "", "intent": null, "is_legal": false}',
    ),
    (
        "날씨가 너무 덥네요",
        '{"law_names": [], "article_no": "", "intent": null, "is_legal": false}',
    ),
]
