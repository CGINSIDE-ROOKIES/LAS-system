from __future__ import annotations

from pydantic import BaseModel, Field

from document_processor.api_types import (
    AnnotationTargetKind,
    AnnotationValidationCode,
    AnnotationValidationIssue,
    AnnotationValidationResult,
    AppliedEditResult,
    ApplyDocumentEditsResult,
    DocumentContextResult,
    DocumentEdit,
    DocumentInput,
    DocumentParagraphContext,
    DocumentRunContext,
    EditableTarget,
    EditValidationCode,
    EditValidationIssue,
    EditValidationResult,
    InsertPosition,
    ListEditableTargetsResult,
    ReadDocumentResult,
    ResolvedTextAnnotation,
    ReviewHtmlResult,
    StructuralEdit,
    StructuralOperationKind,
    StyleEdit,
    StyleTargetKind,
    TargetKind,
    TextAnnotation,
    TextEdit,
    TextTargetKind,
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
    "AnnotationTargetKind",
    "AnnotationValidationCode",
    "AnnotationValidationIssue",
    "AnnotationValidationResult",
    "AppliedEditResult",
    "ApplyDocumentEditsResult",
    "ClauseSummary",
    "DocumentContextResult",
    "DocumentEdit",
    "DocumentInput",
    "DocumentParagraphContext",
    "DocumentRunContext",
    "EditableTarget",
    "EditValidationCode",
    "EditValidationIssue",
    "EditValidationResult",
    "InsertPosition",
    "ListEditableTargetsResult",
    "ParagraphPreview",
    "ParseDocumentResult",
    "ReadDocumentResult",
    "ResolvedTextAnnotation",
    "ReviewHtmlResult",
    "StructuralEdit",
    "StructuralOperationKind",
    "StyleEdit",
    "StyleTargetKind",
    "TargetKind",
    "TextAnnotation",
    "TextEdit",
    "TextTargetKind",
]
