from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RelevanceMode(StrEnum):
    DISABLED = "disabled"
    KEYWORD_ONLY = "keyword_only"
    KEYWORD_THEN_LLM = "keyword_then_llm"


class ParagraphCategory(StrEnum):
    CLAUSE_HEADING = "clause_heading"
    CLAUSE_BODY = "clause_body"
    SUBCLAUSE_HEADING = "subclause_heading"
    SUBCLAUSE_BODY = "subclause_body"
    TITLE = "title"
    HEADER = "header"
    FOOTER = "footer"
    PREAMBLE = "preamble"
    INPUT_BLOCK = "input_block"
    APPENDIX = "appendix"
    OTHER = "other"
    BOUNDARY_SUSPECT = "boundary_suspect"


class NumberingLevel(StrEnum):
    CLAUSE = "clause"
    SUBCLAUSE = "subclause"


class TextSpan(BaseModel):
    start: int
    end: int
    kind: ParagraphCategory
    clause_id: str | None = None
    clause_no: str | None = None
    subclause_id: str | None = None
    subclause_no: str | None = None
    source: str = "regex"
    text: str | None = None


class SplitSuggestion(BaseModel):
    anchor_text: str
    occurrence: int = 1
    left_label: ParagraphCategory
    right_label: ParagraphCategory
    reason: str | None = None


class RelevanceDecision(BaseModel):
    mode: RelevanceMode
    is_relevant: bool
    score: int = 0
    reason: str
    positives: list[str] = Field(default_factory=list)
    negatives: list[str] = Field(default_factory=list)
    llm_used: bool = False
    doc_kind: Literal["contract", "non_contract", "uncertain"] = "uncertain"


class ParserNodeMeta(BaseModel):
    category: ParagraphCategory | None = None
    clause_id: str | None = None
    clause_no: str | None = None
    subclause_id: str | None = None
    subclause_no: str | None = None
    clause_rule_name: str | None = None
    subclause_rule_name: str | None = None
    spans: list[TextSpan] = Field(default_factory=list)
    candidate_labels: list[ParagraphCategory] = Field(default_factory=list)
    boundary_suspect: bool = False
    split_suggestions: list[SplitSuggestion] = Field(default_factory=list)
    confidence: float | None = None
    notes: list[str] = Field(default_factory=list)


class ParagraphAnalysis(BaseModel):
    unit_id: str
    text: str
    page_number: int | None = None
    has_tables: bool = False
    has_images: bool = False
    align: str | None = None
    font_size_pt: float | None = None
    bold_ratio: float | None = None
    clause_id: str | None = None
    clause_no: str | None = None
    subclause_id: str | None = None
    subclause_no: str | None = None
    clause_rule_name: str | None = None
    subclause_rule_name: str | None = None
    spans: list[TextSpan] = Field(default_factory=list)
    category: ParagraphCategory | None = None
    candidate_labels: list[ParagraphCategory] = Field(default_factory=list)
    boundary_suspect: bool = False
    split_suggestions: list[SplitSuggestion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SubclauseEntry(BaseModel):
    subclause_id: str
    subclause_no: str
    start_unit_id: str
    end_unit_id: str
    member_unit_ids: list[str] = Field(default_factory=list)
    spans_by_unit: dict[str, list[TextSpan]] = Field(default_factory=dict)


class ClauseEntry(BaseModel):
    clause_id: str
    clause_no: str
    title: str | None = None
    heading_unit_id: str | None = None
    start_unit_id: str
    end_unit_id: str
    member_unit_ids: list[str] = Field(default_factory=list)
    spans_by_unit: dict[str, list[TextSpan]] = Field(default_factory=dict)
    subclauses: list[SubclauseEntry] = Field(default_factory=list)


class DocTargetRef(BaseModel):
    unit_id: str
    kind: Literal["paragraph", "table", "image", "run", "cell"] = "paragraph"
    page_number: int | None = None
    span_start: int | None = None
    span_end: int | None = None


class ParserDocumentMeta(BaseModel):
    relevance: RelevanceDecision | None = None
    clause_rule_name: str | None = None
    subclause_rule_name: str | None = None
    clause_entries: list[ClauseEntry] = Field(default_factory=list)
    boundary_suspect_unit_ids: list[str] = Field(default_factory=list)
    ambiguous_label_unit_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WorkflowMeta(BaseModel):
    parser: ParserNodeMeta | None = None
    parser_doc: ParserDocumentMeta | None = None
    phase2: dict[str, Any] | None = None
    phase3: dict[str, Any] | None = None


class ParserAnalysis(BaseModel):
    relevance: RelevanceDecision | None = None
    clause_rule_name: str | None = None
    subclause_rule_name: str | None = None
    paragraphs: list[ParagraphAnalysis] = Field(default_factory=list)
    clause_entries: list[ClauseEntry] = Field(default_factory=list)
    boundary_suspect_unit_ids: list[str] = Field(default_factory=list)
    ambiguous_label_unit_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def paragraph_map(self) -> dict[str, ParagraphAnalysis]:
        return {paragraph.unit_id: paragraph for paragraph in self.paragraphs}


class ParserResult(BaseModel):
    accepted: bool
    reason: str
    relevance: RelevanceDecision | None = None
    clause_rule_name: str | None = None
    subclause_rule_name: str | None = None
    clause_count: int = 0
    subclause_count: int = 0
    boundary_suspect_unit_ids: list[str] = Field(default_factory=list)
    ambiguous_label_unit_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WorkflowDelta(BaseModel):
    version: int
    stage: str
    reason: str
