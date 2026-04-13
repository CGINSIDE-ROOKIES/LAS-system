from __future__ import annotations

from pydantic import BaseModel

from document_processor import DocIR

from ..prompts import load_prompt
from ..state import Phase1Config
from ..types import ParagraphAnalysis, ParagraphCategory, Phase1Analysis, SplitSuggestion, WorkflowMeta
from .llm_utils import invoke_structured_model
from .parser import build_clause_entries_from_analysis
from .rules import APPENDIX_MARKER_RE, FOOTER_RE, HEADER_KEYWORD_RE, INPUT_RE
from .selectors import paragraph_lookup, paragraph_position


class BoundaryReviewOutput(BaseModel):
    unit_id: str
    action: str
    reason: str
    anchor_text: str | None = None
    occurrence: int = 1


class BoundaryBatchReviewOutput(BaseModel):
    reviews: list[BoundaryReviewOutput]


def _coarse_boundary_hint(paragraph: ParagraphAnalysis) -> str:
    text = paragraph.text.strip()
    if paragraph.has_tables:
        return "table_like"
    if APPENDIX_MARKER_RE.match(text):
        return "appendix"
    if FOOTER_RE.match(text):
        return "footer"
    if INPUT_RE.search(text) and len(text) <= 120:
        return "input_block"
    if HEADER_KEYWORD_RE.search(text) and len(text) <= 120:
        return "header"
    if paragraph.align == "center" and (paragraph.bold_ratio or 0.0) >= 0.5 and len(text) <= 60:
        return "title"
    return "body"


def detect_boundary_suspects(analysis: Phase1Analysis) -> Phase1Analysis:
    suspect_ids: set[str] = set()
    paragraph_map = paragraph_lookup(analysis.paragraphs)
    clauses_with_subclause_headings = {
        paragraph.clause_id
        for paragraph in analysis.paragraphs
        if paragraph.clause_id
        and any(span.kind == ParagraphCategory.SUBCLAUSE_HEADING for span in paragraph.spans)
    }

    if analysis.clause_entries:
        suspect_ids.update(analysis.clause_entries[-1].member_unit_ids)

    for paragraph in analysis.paragraphs:
        if not paragraph.clause_id or not paragraph.text.strip():
            continue
        if paragraph.unit_id in suspect_ids:
            paragraph.boundary_suspect = True
            paragraph.notes.append("Included in trailing final clause chunk boundary review.")
            continue

        hint = _coarse_boundary_hint(paragraph)
        span_kinds = {span.kind for span in paragraph.spans}
        reasons: list[str] = []
        if hint in {"appendix", "footer", "title", "header"}:
            reasons.append(f"{hint}_like")
        if hint == "input_block" and not paragraph.has_tables:
            reasons.append("input_like")
        if (
            paragraph.text.lstrip().startswith(tuple(f"{value}." for value in range(1, 10)))
            and paragraph.clause_rule_name == "article"
            and paragraph.subclause_rule_name != "numeric_dot"
            and paragraph.clause_id in clauses_with_subclause_headings
        ):
            reasons.append("mismatched_numeric_heading")
        if paragraph.page_number is not None and paragraph.page_number > 1 and hint in {"title", "header"}:
            reasons.append("page_transition_furniture")
        if reasons and span_kinds.isdisjoint({ParagraphCategory.CLAUSE_HEADING, ParagraphCategory.SUBCLAUSE_HEADING}):
            suspect_ids.add(paragraph.unit_id)
            paragraph.boundary_suspect = True
            paragraph.notes.append(f"Boundary suspect: {', '.join(reasons)}.")

    analysis.boundary_suspect_unit_ids = [paragraph.unit_id for paragraph in analysis.paragraphs if paragraph.unit_id in suspect_ids]
    for suspect_id in analysis.boundary_suspect_unit_ids:
        paragraph_map[suspect_id].boundary_suspect = True
    return analysis


def review_boundary_suspects_with_llm(
    doc: DocIR,
    analysis: Phase1Analysis,
    config: Phase1Config,
) -> dict[str, BoundaryReviewOutput]:
    if not config.boundary_review_enabled or not analysis.boundary_suspect_unit_ids:
        return {}

    prompt = load_prompt("phase1/clause_context_boundary_batch", profile=config.prompt_profile)
    blocks = _build_boundary_review_blocks(analysis)
    payload = {"suspect_blocks": blocks}
    output = invoke_structured_model(
        profile=config.boundary_llm_profile,
        prompt=prompt,
        payload=payload,
        schema=BoundaryBatchReviewOutput,
        model_override=config.boundary_model_override,
        config=config,
    )
    reviews = {review.unit_id: review for review in output.reviews if review.unit_id in set(analysis.boundary_suspect_unit_ids)}
    return reviews


def review_single_boundary_suspect_with_llm(
    doc: DocIR,
    analysis: Phase1Analysis,
    unit_id: str,
    config: Phase1Config,
) -> BoundaryReviewOutput:
    prompt = load_prompt("phase1/clause_context_boundary", profile=config.prompt_profile)
    paragraph_map = paragraph_lookup(analysis.paragraphs)
    paragraph = paragraph_map[unit_id]
    index = analysis.paragraphs.index(paragraph)
    prev_text = analysis.paragraphs[index - 1].text if index > 0 else ""
    if prev_text is None:
        prev_text = ""
    next_text = next((candidate.text for candidate in analysis.paragraphs[index + 1 :] if candidate.text.strip()), "")
    payload = {
        "unit_id": paragraph.unit_id,
        "text": paragraph.text,
        "position_in_block": paragraph_position(analysis.paragraphs, paragraph.unit_id),
        "active_clause_no": paragraph.clause_no,
        "active_subclause_no": paragraph.subclause_no,
        "paragraph_label": _coarse_boundary_hint(paragraph),
        "prev": prev_text,
        "next": next_text,
    }
    return invoke_structured_model(
        profile=config.boundary_llm_profile,
        prompt=prompt,
        payload=payload,
        schema=BoundaryReviewOutput,
        model_override=config.boundary_model_override,
        config=config,
    )


def _build_boundary_review_blocks(analysis: Phase1Analysis) -> list[dict[str, object]]:
    paragraphs = analysis.paragraphs
    suspect_ids = set(analysis.boundary_suspect_unit_ids)
    if not suspect_ids:
        return []

    clause_order: list[str] = []
    suspect_indices_by_clause: dict[str, list[int]] = {}
    for index, paragraph in enumerate(paragraphs):
        if paragraph.unit_id not in suspect_ids:
            continue
        clause_id = paragraph.clause_id or f"unit:{paragraph.unit_id}"
        if clause_id not in suspect_indices_by_clause:
            clause_order.append(clause_id)
            suspect_indices_by_clause[clause_id] = []
        suspect_indices_by_clause[clause_id].append(index)

    blocks: list[dict[str, object]] = []
    for clause_id in clause_order:
        suspect_indices = suspect_indices_by_clause[clause_id]
        start_index = max(0, min(suspect_indices) - 1)
        end_index = min(len(paragraphs) - 1, max(suspect_indices) + 1)
        suspect_paragraphs = [paragraphs[index] for index in suspect_indices]
        notes = [
            note
            for paragraph in suspect_paragraphs
            for note in paragraph.notes
            if note not in {"", None}
        ]
        blocks.append(
            {
                "block_id": clause_id,
                "active_clause_no": suspect_paragraphs[0].clause_no,
                "is_trailing_final_clause_chunk": any(
                    "trailing final clause chunk" in note.lower() for note in notes
                ),
                "suspect_unit_ids": [paragraph.unit_id for paragraph in suspect_paragraphs],
                "paragraphs": [
                    {
                        "unit_id": paragraph.unit_id,
                        "text": paragraph.text,
                        "is_suspect": paragraph.unit_id in suspect_ids,
                        "current_kind": paragraph.spans[-1].kind.value if paragraph.spans else None,
                        "active_clause_no": paragraph.clause_no,
                        "active_subclause_no": paragraph.subclause_no,
                        "paragraph_label": _coarse_boundary_hint(paragraph),
                        "page_number": paragraph.page_number,
                    }
                    for paragraph in paragraphs[start_index : end_index + 1]
                ],
            }
        )
    return blocks


def apply_boundary_reviews(analysis: Phase1Analysis, reviews: dict[str, BoundaryReviewOutput]) -> Phase1Analysis:
    if not reviews:
        return analysis

    paragraph_map = paragraph_lookup(analysis.paragraphs)
    for unit_id, review in reviews.items():
        paragraph = paragraph_map.get(unit_id)
        if paragraph is None:
            continue
        paragraph.notes.append(f"Boundary LLM review: {review.reason}")
        if review.action == "keep":
            paragraph.boundary_suspect = False
            continue
        if review.action == "detach":
            paragraph.boundary_suspect = False
            paragraph.clause_id = None
            paragraph.clause_no = None
            paragraph.subclause_id = None
            paragraph.subclause_no = None
            paragraph.spans = []
            continue
        if review.action == "split" and review.anchor_text:
            split_index = _find_occurrence(paragraph.text, review.anchor_text, review.occurrence)
            if split_index is not None and paragraph.spans:
                paragraph.boundary_suspect = False
                last_span = paragraph.spans[-1]
                if split_index > last_span.start:
                    last_span.end = split_index
                    last_span.text = paragraph.text[last_span.start : split_index]
                    paragraph.split_suggestions.append(
                        SplitSuggestion(
                            anchor_text=review.anchor_text,
                            occurrence=review.occurrence,
                            left_label=last_span.kind,
                            right_label=ParagraphCategory.OTHER,
                            reason=review.reason,
                        )
                    )
    analysis.boundary_suspect_unit_ids = [
        paragraph.unit_id for paragraph in analysis.paragraphs if paragraph.boundary_suspect
    ]
    analysis.clause_entries = build_clause_entries_from_analysis(analysis.paragraphs)
    return analysis


def _find_occurrence(text: str, anchor_text: str, occurrence: int) -> int | None:
    start = 0
    for _ in range(max(occurrence, 1)):
        index = text.find(anchor_text, start)
        if index < 0:
            return None
        start = index + len(anchor_text)
    return index
