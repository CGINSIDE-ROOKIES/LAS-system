from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from document_processor.api_types import (
    AnnotationValidationCode,
    AnnotationValidationIssue,
    AnnotationValidationResult,
    ApplyTextEditsRequest,
    ApplyTextEditsResult,
    DocumentContextResult,
    DocumentInput,
    DocumentParagraphContext,
    DocumentRunContext,
    EditableTarget,
    EditValidationCode,
    EditValidationIssue,
    EditValidationResult,
    GetDocumentContextRequest,
    ListEditableTargetsRequest,
    ListEditableTargetsResult,
    RenderReviewHtmlRequest,
    ResolvedTextAnnotation,
    ReviewHtmlResult,
    TargetKind,
    TextAnnotation,
    TextEdit,
    ValidateTextEditsRequest,
)

from .parser_types import ParagraphCategory, RelevanceDecision, RelevanceMode


class ClauseSummary(BaseModel):
    clause_id: str
    clause_no: str
    title: str | None = None
    heading_node_id: str | None = None
    start_node_id: str
    end_node_id: str
    member_node_ids: list[str] = Field(default_factory=list)
    subclause_count: int = 0


class ParagraphPreview(BaseModel):
    node_id: str
    text_excerpt: str
    text_length: int
    page_number: int | None = None
    category: ParagraphCategory | None = None
    clause_id: str | None = None
    clause_no: str | None = None
    subclause_id: str | None = None
    subclause_no: str | None = None
    has_tables: bool = False
    has_images: bool = False
    writable_as_paragraph: bool = False
    run_count: int = 0


class ParseDocumentRequest(BaseModel):
    document: DocumentInput | None = Field(default=None, description="Source document for parser execution.")
    source_path: str | None = Field(
        default=None,
        description="Deprecated convenience field for path-backed calls.",
    )
    relevance_mode: RelevanceMode = Field(default=RelevanceMode.KEYWORD_THEN_LLM)
    boundary_review_enabled: bool = Field(default=True)
    label_review_enabled: bool = Field(default=True)
    prompt_profile: str = Field(default="default")
    include_paragraphs: bool = Field(default=True)
    include_clauses: bool = Field(default=True)
    include_editable_targets: bool = Field(default=False)
    max_paragraphs: int | None = Field(default=120, ge=1)
    max_editable_targets: int | None = Field(default=200, ge=1)
    paragraph_excerpt_length: int | None = Field(default=240, ge=1)

    @model_validator(mode="after")
    def _coerce_document(self) -> "ParseDocumentRequest":
        if self.document is not None and self.source_path is not None:
            raise ValueError("Specify either document or source_path, not both.")
        if self.document is None:
            if self.source_path is None:
                raise ValueError("Provide either document or source_path.")
            self.document = DocumentInput(source_path=self.source_path)
        if self.document.doc_ir is not None:
            raise ValueError("parse_document requires source_path or source_bytes, not doc_ir.")
        return self


class ParseDocumentResult(BaseModel):
    source_path: str | None = None
    source_doc_type: str | None = None
    source_name: str | None = None
    accepted: bool
    reason: str
    relevance: RelevanceDecision | None = None
    clause_count: int = 0
    subclause_count: int = 0
    paragraphs: list[ParagraphPreview] = Field(default_factory=list)
    clauses: list[ClauseSummary] = Field(default_factory=list)
    editable_targets: list[EditableTarget] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "AnnotationValidationCode",
    "AnnotationValidationIssue",
    "AnnotationValidationResult",
    "ApplyTextEditsRequest",
    "ApplyTextEditsResult",
    "ClauseSummary",
    "DocumentContextResult",
    "DocumentInput",
    "DocumentParagraphContext",
    "DocumentRunContext",
    "EditableTarget",
    "EditValidationCode",
    "EditValidationIssue",
    "EditValidationResult",
    "GetDocumentContextRequest",
    "ListEditableTargetsRequest",
    "ListEditableTargetsResult",
    "ParagraphPreview",
    "ParseDocumentRequest",
    "ParseDocumentResult",
    "RenderReviewHtmlRequest",
    "ResolvedTextAnnotation",
    "ReviewHtmlResult",
    "TargetKind",
    "TextAnnotation",
    "TextEdit",
    "ValidateTextEditsRequest",
]
