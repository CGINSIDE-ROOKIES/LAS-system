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

    results: dict[str, BoundaryReviewOutput] = {}
    for unit_id in analysis.boundary_suspect_unit_ids:
        results[unit_id] = review_single_boundary_suspect_with_llm(doc, analysis, unit_id, config)
    return results


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
    prev_text = next((candidate.text for candidate in reversed(analysis.paragraphs[:index]) if candidate.text.strip()), "")
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
