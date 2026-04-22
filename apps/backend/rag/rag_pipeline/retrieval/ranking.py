"""검색 결과 순위 조정 모듈.

RRF 융합 이후 도메인 정책(law 문서 우선 등)을 적용해 최종 순위를 결정한다.
"""

from __future__ import annotations



# law_context_status 상수 (여러 레이어에서 동일 의미로 재사용)
LAW_CONTEXT_OK = "ok"
LAW_CONTEXT_MISSING = "missing"
LAW_CONTEXT_SUPPLEMENTED = "supplemented"
LAW_CONTEXT_CASE_ONLY = "case_only"


def _score_sort_key(row: dict[str, object]) -> tuple[float, str]:
    """score 내림차순 + source_id 오름차순 정렬 키."""
    return (
        -float(row.get("score", 0.0) or 0.0),
        str(row.get("source_id", "") or ""),
    )


# ── Law 문서 점수 가산 ────────────────────────────────────────────────────────

def apply_law_boost(
    rows: list[dict[str, object]],
    *,
    intent: str | None,
    enabled: bool,
    law_boost_score: float,
) -> list[dict[str, object]]:
    """normative intent일 때 law 문서 score에 가산점을 부여하고 재정렬한다."""
    if not enabled or not rows or intent != "normative":
        return rows

    boosted: list[dict[str, object]] = []
    for row in rows:
        score = float(row.get("score", 0.0) or 0.0)
        if str(row.get("doc_type", "") or "") == "law":
            score += law_boost_score
        cloned = dict(row)
        cloned["score"] = score
        boosted.append(cloned)

    boosted.sort(key=_score_sort_key)
    for i, row in enumerate(boosted, start=1):
        row["rank"] = i
    return boosted


# ── 점수 기반 재정렬 ──────────────────────────────────────────────────────────

def rank_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """score 내림차순 + source_id 오름차순으로 재정렬하고 rank를 재부여한다."""
    ranked = sorted((dict(r) for r in rows), key=_score_sort_key)
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked


# ── LLM 입력 행 선택 ──────────────────────────────────────────────────────────

def select_llm_rows(
    rows: list[dict[str, object]],
    *,
    top_k: int,
    min_law_contexts: int,
) -> tuple[list[dict[str, object]], bool]:
    """LLM에 넘길 행을 선택하고, 최소 law 문서 수 충족 여부를 함께 반환한다.

    참고: 현재 rag_pipeline 경로에서는 `select_rows_with_law_policy()`를 사용한다.
    이 함수는 단순 선택 정책이 필요한 호출부와의 하위호환을 위해 유지한다.
    """
    selected = list(rows[: max(1, top_k)])
    if min_law_contexts <= 0:
        return selected, True
    law_count = sum(1 for r in selected if str(r.get("doc_type", "") or "") == "law")
    return selected, law_count >= min_law_contexts


def select_rows_with_law_policy(
    rows: list[dict[str, object]],
    *,
    top_k: int,
    min_law_contexts: int,
    enforce_min_law_contexts: bool,
) -> tuple[list[dict[str, object]], str, bool]:
    """LLM에 넘길 행을 선택하고, law 문서 최소 수 정책을 적용한다.

    enforce_min_law_contexts=True이면 top_k 바깥의 law 문서를 끌어와
    non-law 문서와 교체하는 보강을 시도한다.

    Returns:
        (selected_rows, law_context_status, law_context_added)
        law_context_status: LAW_CONTEXT_OK | LAW_CONTEXT_MISSING |
                            LAW_CONTEXT_SUPPLEMENTED | LAW_CONTEXT_CASE_ONLY
    """
    selected = list(rows[: max(1, top_k)])
    if min_law_contexts <= 0:
        return rank_rows(selected), LAW_CONTEXT_OK, True

    law_count = sum(1 for r in selected if str(r.get("doc_type", "") or "") == "law")
    if law_count >= min_law_contexts:
        return rank_rows(selected), LAW_CONTEXT_OK, True

    if not enforce_min_law_contexts:
        # 조문 0건이고 판례/해석례만 존재하는 경우
        if law_count == 0 and len(selected) > 0:
            return rank_rows(selected), LAW_CONTEXT_CASE_ONLY, False
        return rank_rows(selected), LAW_CONTEXT_MISSING, False

    # top_k 바깥에서 law 문서 후보 수집
    selected_ids = {str(r.get("source_id", "") or "") for r in selected}
    extra_law_pool: list[dict[str, object]] = []
    for row in rows[max(1, top_k):]:
        if str(row.get("doc_type", "") or "") != "law":
            continue
        source_id = str(row.get("source_id", "") or "")
        if source_id and source_id in selected_ids:
            continue
        extra_law_pool.append(dict(row))
    # 입력 rows의 rank/score 순서를 그대로 신뢰하지 않고, 보강 후보는 안정적으로 정렬한다.
    extra_law_pool = rank_rows(extra_law_pool)

    needed = max(0, min_law_contexts - law_count)
    replacements = min(needed, len(extra_law_pool))
    if replacements <= 0:
        return rank_rows(selected), LAW_CONTEXT_MISSING, False

    non_law_indexes = [i for i, r in enumerate(selected) if str(r.get("doc_type", "") or "") != "law"]
    if not non_law_indexes:
        return rank_rows(selected), LAW_CONTEXT_MISSING, False

    # 낮은 우선순위 문서부터 교체하기 위해 뒤쪽(non-law) 슬롯부터 치환한다.
    # 이렇게 하면 기존 top-ranked law 문서를 보존하면서 최소 law 개수만 보강할 수 있다.
    replace_slots = list(reversed(non_law_indexes))[:replacements]
    for slot, law_row in zip(replace_slots, extra_law_pool[:replacements]):
        selected[slot] = law_row

    selected_ranked = rank_rows(selected)
    final_law_count = sum(1 for r in selected_ranked if str(r.get("doc_type", "") or "") == "law")
    if final_law_count >= min_law_contexts:
        return selected_ranked, LAW_CONTEXT_SUPPLEMENTED, True
    return selected_ranked, LAW_CONTEXT_MISSING, False
