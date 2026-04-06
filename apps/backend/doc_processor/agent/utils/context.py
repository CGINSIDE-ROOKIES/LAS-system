from __future__ import annotations

from typing import Any

try:
    from ...processor_types import ParagraphIR
except ImportError:  # pragma: no cover - top-level import mode in local tests
    from processor_types import ParagraphIR


def token_count(model: Any, text: str) -> int:
    if not text:
        return 0
    counter = getattr(model, "get_num_tokens", None)
    if callable(counter):
        try:
            return max(0, int(counter(text)))
        except Exception:
            pass
    return max(1, int(round(len(text) * 0.8)))


def clip_to_budget(
    text: str,
    *,
    budget: int,
    model: Any,
    keep_tail: bool,
) -> tuple[str, bool]:
    if budget <= 0:
        return "", bool(text)
    if token_count(model, text) <= budget:
        return text, False

    lo = 0
    hi = len(text)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[-mid:] if keep_tail else text[:mid]
        if token_count(model, candidate) <= budget:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best, True


def nearest_non_empty_idx(paragraphs: list[ParagraphIR], start_idx: int, step: int) -> int | None:
    idx = start_idx + step
    while 0 <= idx < len(paragraphs):
        if (paragraphs[idx].text or "").strip():
            return idx
        idx += step
    return None


def build_neighbor_context(
    paragraphs: list[ParagraphIR],
    *,
    paragraph_idx: int,
    budget: int,
    model: Any,
) -> tuple[str, str | None, str | None]:
    left_idx = nearest_non_empty_idx(paragraphs, paragraph_idx, -1)
    right_idx = nearest_non_empty_idx(paragraphs, paragraph_idx, +1)

    if left_idx is not None and right_idx is not None:
        left_budget = budget // 2
        right_budget = budget - left_budget
    elif left_idx is not None:
        left_budget = budget
        right_budget = 0
    else:
        left_budget = 0
        right_budget = budget

    if left_idx is None:
        prev_text = None
        position = "start"
    else:
        prev_text, _ = clip_to_budget(
            paragraphs[left_idx].text,
            budget=left_budget,
            model=model,
            keep_tail=True,
        )

    if right_idx is None:
        next_text = None
        position = "end" if left_idx is not None else "only"
    else:
        next_text, _ = clip_to_budget(
            paragraphs[right_idx].text,
            budget=right_budget,
            model=model,
            keep_tail=False,
        )

    if left_idx is not None and right_idx is not None:
        position = "middle"

    return position, prev_text, next_text
