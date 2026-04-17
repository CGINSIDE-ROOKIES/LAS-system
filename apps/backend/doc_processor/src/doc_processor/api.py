from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from document_processor import DocIR, DocumentInput
from document_processor.api import (
    apply_text_edits,
    get_document_context,
    list_editable_targets,
    render_review_html,
    validate_text_edits,
)
from document_processor.edit_engine import _iter_doc_ir_paragraphs
from document_processor.io_utils import TemporarySourcePath

from .api_types import (
    AnnotationValidationCode,
    AnnotationValidationIssue,
    AnnotationValidationResult,
    ApplyTextEditsRequest,
    ApplyTextEditsResult,
    ClauseSummary,
    DocumentContextResult,
    DocumentParagraphContext,
    DocumentRunContext,
    EditableTarget,
    EditValidationCode,
    EditValidationIssue,
    EditValidationResult,
    GetDocumentContextRequest,
    ListEditableTargetsRequest,
    ListEditableTargetsResult,
    ParagraphPreview,
    ParseDocumentRequest,
    ParseDocumentResult,
    RenderReviewHtmlRequest,
    ResolvedTextAnnotation,
    ReviewHtmlResult,
    TargetKind,
    TextAnnotation,
    TextEdit,
    ValidateTextEditsRequest,
)
from .main import run_parser
from .parser_types import ClauseEntry
from .state import ParserConfig


def parse_document(request: ParseDocumentRequest) -> ParseDocumentResult:
    with _materialize_parse_source(request.document) as source_path:
        state = run_parser(
            source_path,
            config=ParserConfig(
                relevance_mode=request.relevance_mode,
                boundary_review_enabled=request.boundary_review_enabled,
                label_review_enabled=request.label_review_enabled,
                prompt_profile=request.prompt_profile,
            ),
        )

    result = state.parser_result
    if result is None:
        raise ValueError("Parser did not produce a parser_result.")

    doc = state.working_doc
    if doc is None:
        raise ValueError("Parser did not produce a working_doc.")

    requested_source_path = request.document.source_path
    requested_source_name = (
        request.document.source_name
        or (Path(requested_source_path).name if requested_source_path is not None else None)
    )
    response = ParseDocumentResult(
        source_path=requested_source_path,
        source_doc_type=doc.source_doc_type,
        source_name=requested_source_name,
        accepted=result.accepted,
        reason=result.reason,
        relevance=result.relevance,
        clause_count=result.clause_count,
        subclause_count=result.subclause_count,
        warnings=[*state.errors, *result.notes],
    )

    if request.include_clauses and state.parser_analysis is not None:
        response.clauses = [_clause_summary(entry) for entry in state.parser_analysis.clause_entries]

    if request.include_paragraphs and state.parser_analysis is not None:
        paragraphs = state.parser_analysis.paragraphs
        if request.max_paragraphs is not None:
            paragraphs = paragraphs[: request.max_paragraphs]
        response.paragraphs = [
            ParagraphPreview(
                unit_id=paragraph.unit_id,
                text_excerpt=_truncate(paragraph.text, request.paragraph_excerpt_length),
                text_length=len(paragraph.text),
                page_number=paragraph.page_number,
                category=paragraph.category,
                clause_id=paragraph.clause_id,
                clause_no=paragraph.clause_no,
                subclause_id=paragraph.subclause_id,
                subclause_no=paragraph.subclause_no,
                has_tables=paragraph.has_tables,
                has_images=paragraph.has_images,
                writable_as_paragraph=not (paragraph.has_tables or paragraph.has_images),
                run_count=len(_find_paragraph_runs(doc, paragraph.unit_id)),
            )
            for paragraph in paragraphs
        ]

    if request.include_editable_targets:
        response.editable_targets = list_editable_targets(
            ListEditableTargetsRequest(
                document=DocumentInput(doc_ir=doc),
                target_kinds=["paragraph", "run"],
                only_writable=True,
                max_targets=request.max_editable_targets,
            )
        ).targets

    return response


@contextmanager
def _materialize_parse_source(document: DocumentInput):
    if document.source_path is not None:
        yield Path(document.source_path)
        return
    if document.source_bytes is None:
        raise ValueError("parse_document requires source_path or source_bytes.")

    suffix = _parse_suffix(document)
    with TemporarySourcePath(document.source_bytes, suffix=suffix) as source_path:
        yield source_path


def _parse_suffix(document: DocumentInput) -> str:
    if document.source_name:
        suffix = Path(document.source_name).suffix
        if suffix:
            return suffix
    if document.source_doc_type == "docx":
        return ".docx"
    if document.source_doc_type == "hwpx":
        return ".hwpx"
    if document.source_doc_type == "hwp":
        return ".hwp"
    if document.source_doc_type == "pdf":
        return ".pdf"
    raise ValueError("parse_document bytes input requires source_name or source_doc_type.")


def _clause_summary(entry: ClauseEntry) -> ClauseSummary:
    return ClauseSummary(
        clause_id=entry.clause_id,
        clause_no=entry.clause_no,
        title=entry.title,
        heading_unit_id=entry.heading_unit_id,
        start_unit_id=entry.start_unit_id,
        end_unit_id=entry.end_unit_id,
        member_unit_ids=entry.member_unit_ids,
        subclause_count=len(entry.subclauses),
    )


def _truncate(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _find_paragraph_runs(doc: DocIR, paragraph_unit_id: str):
    for paragraph in _iter_doc_ir_paragraphs(doc.paragraphs):
        if paragraph.unit_id == paragraph_unit_id:
            return paragraph.runs
    return []


__all__ = [
    "AnnotationValidationCode",
    "AnnotationValidationIssue",
    "AnnotationValidationResult",
    "ApplyTextEditsRequest",
    "ApplyTextEditsResult",
    "ClauseSummary",
    "DocumentContextResult",
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
    "apply_text_edits",
    "get_document_context",
    "list_editable_targets",
    "parse_document",
    "render_review_html",
    "validate_text_edits",
]
