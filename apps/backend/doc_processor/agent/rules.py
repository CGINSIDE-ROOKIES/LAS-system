"""Rule-based pre-labeling for paragraphs with high-confidence regex signals."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..processor_types import DocIR, ParagraphIR

try:
    from ..processor_types import ParagraphReviewResult, SplitOp
except ImportError:  # pragma: no cover - top-level import mode in local tests
    from processor_types import ParagraphReviewResult, SplitOp


def _try_clause_subclause_rule(paragraph: ParagraphIR) -> ParagraphReviewResult | None:
    """Apply clause/subclause rules based on regex signals.

    Returns a synthetic ParagraphReviewResult if the rule matches, None otherwise.
    """
    signals = paragraph.parser_signals
    if signals is None:
        return None

    has_clause = signals.regex_clause is not None
    has_subclause = signals.regex_subclause is not None

    if has_clause and has_subclause:
        # Auto-split: clause heading + subclause body
        sc = signals.regex_subclause
        anchor_text = sc.matched_text
        return ParagraphReviewResult(
            unit_id=paragraph.unit_id,
            status="split",
            label="clause",
            candidate_labels=["clause", "subclause"],
            reason=f"regex: clause {signals.regex_clause.matched_text} + subclause {anchor_text}",
            ops=[
                SplitOp(
                    anchor_text=anchor_text,
                    occurrence=1,
                    left_label="clause",
                    right_label="subclause",
                    left_candidate_labels=["clause"],
                    right_candidate_labels=["subclause"],
                ),
            ],
        )

    if has_clause:
        return ParagraphReviewResult(
            unit_id=paragraph.unit_id,
            status="ok",
            label="clause",
            candidate_labels=["clause"],
            reason=f"regex: {signals.regex_clause.matched_text}",
        )

    if has_subclause:
        return ParagraphReviewResult(
            unit_id=paragraph.unit_id,
            status="ok",
            label="subclause",
            candidate_labels=["subclause"],
            reason=f"regex: {signals.regex_subclause.matched_text}",
        )

    return None


def apply_rule_labels(
    doc_ir: DocIR,
) -> tuple[list[int], list[int]]:
    """Pre-label paragraphs using deterministic rules.

    Ensures numbering signals are populated before applying rules.

    Returns:
        (resolved_indices, unresolved_indices) — resolved paragraphs have their
        review result applied in-place; unresolved paragraphs need LLM processing.
    """
    # Ensure regex clause/subclause signals are populated.
    doc_ir.annotate_numbering_signals()

    resolved: list[int] = []
    unresolved: list[int] = []

    for idx, paragraph in enumerate(doc_ir.paragraphs):
        if not (paragraph.text or "").strip():
            continue

        result = _try_clause_subclause_rule(paragraph)
        if result is not None:
            paragraph.apply_review_result(result, strict=False)
            resolved.append(idx)
        else:
            unresolved.append(idx)

    return resolved, unresolved
