from __future__ import annotations

from pydantic import BaseModel, Field

from document_processor import DocIR

from ..prompts import load_prompt
from ..state import ParserConfig
from ..types import ParagraphAnalysis, ParagraphCategory, ParserAnalysis, SplitSuggestion, WorkflowMeta
from .llm_utils import invoke_structured_model
from .rules import APPENDIX_MARKER_RE, FOOTER_RE, HEADER_KEYWORD_RE, INPUT_RE
from .selectors import paragraph_position


class LabelSplitOp(BaseModel):
    op: str
    anchor_text: str
    occurrence: int = 1
    left_label: str
    right_label: str


class LabelReviewOutput(BaseModel):
    unit_id: str
    status: str
    label: str
    candidate_labels: list[str] = Field(default_factory=list)
    reason: str
    ops: list[LabelSplitOp] = Field(default_factory=list)


_CLAUSE_CONTEXT_CATEGORIES = {
    ParagraphCategory.CLAUSE_HEADING,
    ParagraphCategory.CLAUSE_BODY,
    ParagraphCategory.SUBCLAUSE_HEADING,
    ParagraphCategory.SUBCLAUSE_BODY,
}


def label_paragraphs(analysis: ParserAnalysis) -> ParserAnalysis:
    first_clause_index = next(
        (index for index, paragraph in enumerate(analysis.paragraphs) if paragraph.clause_id is not None),
        None,
    )
    ambiguous: list[str] = []
    for index, paragraph in enumerate(analysis.paragraphs):
        category, candidates, notes, is_ambiguous = _deterministic_label(
            paragraph,
            before_first_clause=first_clause_index is not None and index < first_clause_index,
        )
        paragraph.category = category
        paragraph.candidate_labels = candidates
        paragraph.notes.extend(notes)
        if is_ambiguous:
            ambiguous.append(paragraph.unit_id)
    analysis.ambiguous_label_unit_ids = ambiguous
    return analysis


def review_ambiguous_labels_with_llm(
    doc: DocIR,
    analysis: ParserAnalysis,
    config: ParserConfig,
) -> dict[str, LabelReviewOutput]:
    if not config.label_review_enabled or not analysis.ambiguous_label_unit_ids:
        return {}

    results: dict[str, LabelReviewOutput] = {}

    for unit_id in analysis.ambiguous_label_unit_ids:
        results[unit_id] = review_single_ambiguous_label_with_llm(doc, analysis, unit_id, config)
    return results


def review_single_ambiguous_label_with_llm(
    doc: DocIR,
    analysis: ParserAnalysis,
    unit_id: str,
    config: ParserConfig,
) -> LabelReviewOutput:
    prompt = load_prompt("parser/paragraph_labeler", profile=config.prompt_profile)
    paragraph_map = {paragraph.unit_id: paragraph for paragraph in analysis.paragraphs}
    paragraph = paragraph_map[unit_id]
    index = analysis.paragraphs.index(paragraph)
    prev_text = next((candidate.text for candidate in reversed(analysis.paragraphs[:index]) if candidate.text.strip()), "")
    next_text = next((candidate.text for candidate in analysis.paragraphs[index + 1 :] if candidate.text.strip()), "")
    payload = {
        "unit_id": paragraph.unit_id,
        "text": paragraph.text,
        "position": paragraph_position(analysis.paragraphs, paragraph.unit_id),
        "signals": {
            "clause_no": paragraph.clause_no,
            "subclause_no": paragraph.subclause_no,
            "active_clause_no": paragraph.clause_no,
            "active_subclause_no": paragraph.subclause_no,
            "bold_ratio": paragraph.bold_ratio,
            "centered": paragraph.align == "center",
            "font_size": paragraph.font_size_pt,
            "boundary_suspect": paragraph.boundary_suspect,
            "has_tables": paragraph.has_tables,
            "has_images": paragraph.has_images,
        },
        "prev": prev_text,
        "next": next_text,
    }
    return invoke_structured_model(
        profile=config.label_llm_profile,
        prompt=prompt,
        payload=payload,
        schema=LabelReviewOutput,
        model_override=config.label_model_override,
        config=config,
    )


def apply_label_reviews(analysis: ParserAnalysis, reviews: dict[str, LabelReviewOutput]) -> ParserAnalysis:
    if not reviews:
        return analysis

    paragraph_map = {paragraph.unit_id: paragraph for paragraph in analysis.paragraphs}
    for unit_id, review in reviews.items():
        paragraph = paragraph_map.get(unit_id)
        if paragraph is None:
            continue
        paragraph.notes.append(f"Label LLM review: {review.reason}")
        try:
            paragraph.category = ParagraphCategory(review.label)
        except ValueError:
            paragraph.notes.append(f"Unrecognized LLM label '{review.label}', keeping deterministic label.")
        candidates: list[ParagraphCategory] = []
        for candidate in review.candidate_labels:
            try:
                candidates.append(ParagraphCategory(candidate))
            except ValueError:
                continue
        if candidates:
            paragraph.candidate_labels = candidates
        for op in review.ops:
            if op.op != "split_unit":
                continue
            try:
                left_label = ParagraphCategory(op.left_label)
                right_label = ParagraphCategory(op.right_label)
            except ValueError:
                continue
            paragraph.split_suggestions.append(
                SplitSuggestion(
                    anchor_text=op.anchor_text,
                    occurrence=op.occurrence,
                    left_label=left_label,
                    right_label=right_label,
                    reason=review.reason,
                )
            )
        _normalize_clause_context_for_category(paragraph)

    analysis.ambiguous_label_unit_ids = [
        paragraph.unit_id
        for paragraph in analysis.paragraphs
        if paragraph.unit_id not in reviews
    ]
    return analysis


def _normalize_clause_context_for_category(paragraph: ParagraphAnalysis) -> None:
    if paragraph.category in _CLAUSE_CONTEXT_CATEGORIES:
        return
    paragraph.clause_id = None
    paragraph.clause_no = None
    paragraph.subclause_id = None
    paragraph.subclause_no = None
    paragraph.clause_rule_name = None
    paragraph.subclause_rule_name = None
    paragraph.spans = [
        span
        for span in paragraph.spans
        if span.kind not in {
            ParagraphCategory.CLAUSE_HEADING,
            ParagraphCategory.CLAUSE_BODY,
            ParagraphCategory.SUBCLAUSE_HEADING,
            ParagraphCategory.SUBCLAUSE_BODY,
        }
    ]


def _deterministic_label(
    paragraph: ParagraphAnalysis,
    *,
    before_first_clause: bool,
) -> tuple[ParagraphCategory, list[ParagraphCategory], list[str], bool]:
    text = paragraph.text.strip()
    notes: list[str] = []
    candidates: list[ParagraphCategory] = []
    ambiguous = False

    if not text:
        return ParagraphCategory.OTHER, [ParagraphCategory.OTHER], notes, False
    if paragraph.boundary_suspect:
        return ParagraphCategory.BOUNDARY_SUSPECT, [ParagraphCategory.BOUNDARY_SUSPECT], notes, False
    if APPENDIX_MARKER_RE.match(text):
        return ParagraphCategory.APPENDIX, [ParagraphCategory.APPENDIX], notes, False
    if FOOTER_RE.match(text):
        return ParagraphCategory.FOOTER, [ParagraphCategory.FOOTER], notes, False

    title_like = (
        paragraph.align == "center"
        and (paragraph.bold_ratio or 0.0) >= 0.5
        and len(text) <= 80
    )
    header_like = HEADER_KEYWORD_RE.search(text) is not None and len(text) <= 120
    input_like = INPUT_RE.search(text) is not None

    span_kinds = {span.kind for span in paragraph.spans}
    if ParagraphCategory.CLAUSE_HEADING in span_kinds:
        return ParagraphCategory.CLAUSE_HEADING, [ParagraphCategory.CLAUSE_HEADING], notes, False
    if ParagraphCategory.SUBCLAUSE_HEADING in span_kinds:
        return ParagraphCategory.SUBCLAUSE_HEADING, [ParagraphCategory.SUBCLAUSE_HEADING], notes, False
    if paragraph.subclause_id:
        return ParagraphCategory.SUBCLAUSE_BODY, [ParagraphCategory.SUBCLAUSE_BODY], notes, False
    if paragraph.clause_id:
        return ParagraphCategory.CLAUSE_BODY, [ParagraphCategory.CLAUSE_BODY], notes, False
    if input_like and len(text) <= 240:
        return ParagraphCategory.INPUT_BLOCK, [ParagraphCategory.INPUT_BLOCK, ParagraphCategory.OTHER], notes, False
    if before_first_clause:
        if title_like:
            return ParagraphCategory.TITLE, [ParagraphCategory.TITLE], notes, False
        if header_like:
            return ParagraphCategory.HEADER, [ParagraphCategory.HEADER, ParagraphCategory.PREAMBLE], notes, False
        return ParagraphCategory.PREAMBLE, [ParagraphCategory.PREAMBLE], notes, False
    if header_like and paragraph.page_number is not None and paragraph.page_number > 1:
        return ParagraphCategory.HEADER, [ParagraphCategory.HEADER, ParagraphCategory.OTHER], notes, False
    if title_like and paragraph.page_number is not None and paragraph.page_number > 1:
        candidates = [ParagraphCategory.TITLE, ParagraphCategory.OTHER]
        notes.append("Centered/bold short paragraph inside later pages.")
        ambiguous = True
        return ParagraphCategory.TITLE, candidates, notes, ambiguous

    candidates = [ParagraphCategory.OTHER]
    if title_like:
        candidates.append(ParagraphCategory.TITLE)
    if header_like:
        candidates.append(ParagraphCategory.HEADER)
    notes.append("No active clause context and no decisive structural signal.")
    ambiguous = len(candidates) > 1 or not before_first_clause
    return ParagraphCategory.OTHER, candidates, notes, ambiguous
