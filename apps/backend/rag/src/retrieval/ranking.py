"""검색 결과 순위 조정 모듈.

RRF 융합 이후 도메인 정책(law 문서 우선 등)을 적용해 최종 순위를 결정한다.
"""

from __future__ import annotations


# ── 규범형 질의 판별 ───────────────────────────────────────────────────────────

_NORMATIVE_KEYWORDS = (
    "기준", "요건", "의무", "절차", "서면", "신청", "작성",
    "반드시", "해야", "가능", "조건",
)


def is_normative_query(question: str) -> bool:
    """기준·요건·의무 등 규범형 질의인지 판별한다."""
    return any(k in question.strip() for k in _NORMATIVE_KEYWORDS)


# ── Law 문서 점수 가산 ────────────────────────────────────────────────────────

def apply_law_boost(
    rows: list[dict[str, object]],
    *,
    question: str,
    enabled: bool,
    law_boost_score: float,
) -> list[dict[str, object]]:
    """규범형 질의일 때 law 문서 score에 가산점을 부여하고 재정렬한다."""
    if not enabled or not rows or not is_normative_query(question):
        return rows

    boosted: list[dict[str, object]] = []
    for row in rows:
        score = float(row.get("score", 0.0) or 0.0)
        if str(row.get("doc_type", "") or "") == "law":
            score += law_boost_score
        cloned = dict(row)
        cloned["score"] = score
        boosted.append(cloned)

    boosted.sort(
        key=lambda r: (
            -float(r.get("score", 0.0) or 0.0),
            str(r.get("source_id", "") or ""),
        )
    )
    for i, row in enumerate(boosted, start=1):
        row["rank"] = i
    return boosted


# ── LLM 입력 행 선택 ──────────────────────────────────────────────────────────

def select_llm_rows(
    rows: list[dict[str, object]],
    *,
    top_k: int,
    min_law_contexts: int,
) -> tuple[list[dict[str, object]], bool]:
    """LLM에 넘길 행을 선택하고, 최소 law 문서 수 충족 여부를 함께 반환한다."""
    selected = list(rows[: max(1, top_k)])
    if min_law_contexts <= 0:
        return selected, True
    law_count = sum(1 for r in selected if str(r.get("doc_type", "") or "") == "law")
    return selected, law_count >= min_law_contexts
