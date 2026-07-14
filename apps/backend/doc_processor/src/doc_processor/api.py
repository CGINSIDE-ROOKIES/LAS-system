from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from document_processor import DocIR, DocumentInput
from document_processor.api import (
    apply_document_edits,
    get_document_context,
    list_editable_targets,
    read_document,
    render_review_html,
    validate_document_edits,
    validate_text_annotations,
)
from document_processor.edit_engine import _iter_doc_ir_paragraphs
from document_processor.io_utils import TemporarySourcePath

from .api_types import (
    AnnotationTargetKind,
    AnnotationValidationCode,
    AnnotationValidationIssue,
    AnnotationValidationResult,
    AppliedEditResult,
    ApplyDocumentEditsResult,
    ClauseSummary,
    DocumentContextResult,
    DocumentEdit,
    DocumentParagraphContext,
    DocumentRunContext,
    EditableTarget,
    EditValidationCode,
    EditValidationIssue,
    EditValidationResult,
    InsertPosition,
    ListEditableTargetsResult,
    ParagraphPreview,
    ParseDocumentResult,
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
from .main import run_parser
from .parser_types import ClauseEntry, RelevanceMode
from .state import ParserConfig


def parse_document(
    *,
    document: DocumentInput | None = None,
    source_path: str | Path | None = None,
    relevance_mode: RelevanceMode = RelevanceMode.KEYWORD_THEN_LLM,
    boundary_review_enabled: bool = True,
    label_review_enabled: bool = True,
    max_concurrent_workers: int = 4,
    llm_repair_max_attempts: int = 3,
    prompt_profile: str = "default",
    include_paragraphs: bool = True,
    include_clauses: bool = True,
    include_editable_targets: bool = False,
    max_paragraphs: int | None = 120,
    max_editable_targets: int | None = 200,
    paragraph_excerpt_length: int | None = 240,
) -> ParseDocumentResult:
    source = _resolve_parse_document(document=document, source_path=source_path)
    with _materialize_parse_source(source) as materialized_source_path:
        state = run_parser(
            materialized_source_path,
            config=ParserConfig(
                relevance_mode=relevance_mode,
                boundary_review_enabled=boundary_review_enabled,
                label_review_enabled=label_review_enabled,
                max_concurrent_workers=max_concurrent_workers,
                llm_repair_max_attempts=llm_repair_max_attempts,
                prompt_profile=prompt_profile,
            ),
        )

    result = state.parser_result
    if result is None:
        raise ValueError("Parser did not produce a parser_result.")

    doc = state.working_doc
    if doc is None:
        raise ValueError("Parser did not produce a working_doc.")

    requested_source_path = str(source.source_path) if source.source_path is not None else None
    requested_source_name = (
        source.source_name
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

    if include_clauses and state.parser_analysis is not None:
        response.clauses = [_clause_summary(entry) for entry in state.parser_analysis.clause_entries]

    if include_paragraphs and state.parser_analysis is not None:
        paragraphs = state.parser_analysis.paragraphs
        if max_paragraphs is not None:
            paragraphs = paragraphs[:max_paragraphs]
        response.paragraphs = [
            ParagraphPreview(
                node_id=paragraph.node_id,
                text_excerpt=_truncate(paragraph.text, paragraph_excerpt_length),
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
                run_count=len(_find_paragraph_runs(doc, paragraph.node_id)),
            )
            for paragraph in paragraphs
        ]

    if include_editable_targets:
        response.editable_targets = list_editable_targets(
            document=DocumentInput(doc_ir=doc),
            target_kinds=["paragraph", "run"],
            only_writable=True,
            max_targets=max_editable_targets,
        ).targets

    return response


def _resolve_parse_document(
    *,
    document: DocumentInput | None,
    source_path: str | Path | None,
) -> DocumentInput:
    if document is not None and source_path is not None:
        raise ValueError("Specify either document or source_path, not both.")
    if document is None:
        if source_path is None:
            raise ValueError("Provide either document or source_path.")
        document = DocumentInput(source_path=source_path)
    if document.doc_ir is not None:
        raise ValueError("parse_document requires source_path or source_bytes, not doc_ir.")
    return document


@contextmanager
def _materialize_parse_source(document: DocumentInput):
    if document.source_path is not None:
        yield Path(document.source_path)
        return
    if document.source_bytes is None:
        raise ValueError("parse_document requires source_path or source_bytes.")

    suffix = _parse_suffix(document)
    with TemporarySourcePath(document.source_bytes, suffix=suffix) as materialized_source_path:
        yield materialized_source_path


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
        heading_node_id=entry.heading_node_id,
        start_node_id=entry.start_node_id,
        end_node_id=entry.end_node_id,
        member_node_ids=entry.member_node_ids,
        subclause_count=len(entry.subclauses),
    )


def _truncate(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _find_paragraph_runs(doc: DocIR, paragraph_node_id: str):
    for paragraph in _iter_doc_ir_paragraphs(doc.paragraphs):
        if paragraph.node_id == paragraph_node_id:
            return paragraph.runs
    return []


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
    "apply_document_edits",
    "get_document_context",
    "list_editable_targets",
    "parse_document",
    "read_document",
    "render_review_html",
    "validate_document_edits",
    "validate_text_annotations",
]
