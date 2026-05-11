from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Iterable

from doc_processor.api import ParseDocumentResult, TextAnnotation, TextEdit, render_review_html
from doc_processor.contract_review import ContractReviewFinding, ContractReviewResult

_CATEGORY_COLORS = {
    "clause_heading": "#A7F3D0",
    "clause_body": "#BFDBFE",
    "subclause_heading": "#DDD6FE",
    "subclause_body": "#E9D5FF",
    "title": "#FDE68A",
    "header": "#E5E7EB",
    "footer": "#E5E7EB",
    "preamble": "#FED7AA",
    "input_block": "#FECACA",
    "appendix": "#C7D2FE",
    "other": "#F3F4F6",
    "boundary_suspect": "#FCA5A5",
}


def render_original_preview(source_path: str | Path, *, title: str = "원본 문서") -> str:
    return _render(source_path=source_path, annotations=[], title=title)


def render_parser_preview(source_path: str | Path, parse_result: ParseDocumentResult) -> str:
    return _render(
        source_path=source_path,
        annotations=list(_parser_annotations(parse_result)),
        title="문서 구조 분석",
    )


def render_risk_preview(source_path: str | Path, review_result: ContractReviewResult) -> str:
    if review_result.review_html:
        return review_result.review_html
    annotations = [
        finding.annotation
        for finding in review_result.findings
        if finding.annotation is not None
    ]
    return _render(source_path=source_path, annotations=annotations, title=review_result.risk_level.upper())


def render_edited_preview(source_path: str | Path, edits: list[TextEdit]) -> str:
    annotations = [
        TextAnnotation(
            target_kind=edit.target_kind,
            target_id=edit.target_id,
            label="수정됨",
            color="#86EFAC",
            note=edit.reason or "Accepted document review edit.",
        )
        for edit in _unique_target_edits(edits)
    ]
    return _render(source_path=source_path, annotations=annotations, title="수정 문서")


def _parser_annotations(parse_result: ParseDocumentResult) -> Iterable[TextAnnotation]:
    for paragraph in parse_result.paragraphs:
        category = str(paragraph.category or "other")
        label_parts = []
        if paragraph.clause_no:
            label_parts.append(f"제{paragraph.clause_no}조")
        if paragraph.subclause_no:
            label_parts.append(paragraph.subclause_no)
        label_parts.append(category)
        note_parts = []
        if paragraph.clause_id:
            note_parts.append(f"clause_id: {paragraph.clause_id}")
        if paragraph.subclause_id:
            note_parts.append(f"subclause_id: {paragraph.subclause_id}")
        if paragraph.page_number is not None:
            note_parts.append(f"page: {paragraph.page_number}")
        yield TextAnnotation(
            target_kind="paragraph",
            target_id=paragraph.node_id,
            label=" / ".join(label_parts),
            color=_CATEGORY_COLORS.get(category, "#F3F4F6"),
            note="\n".join(note_parts),
        )


def _unique_target_edits(edits: list[TextEdit]) -> list[TextEdit]:
    seen: set[tuple[str, str]] = set()
    unique: list[TextEdit] = []
    for edit in edits:
        key = (str(edit.target_kind), edit.target_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(edit)
    return unique


def _render(*, source_path: str | Path, annotations: list[TextAnnotation], title: str) -> str:
    result = render_review_html(source_path=source_path, annotations=annotations, title=title)
    if result.ok and result.html:
        return result.html
    issues = [
        getattr(issue, "message", str(issue))
        for issue in getattr(result.validation, "issues", [])
    ]
    return _fallback_html(title=title, issues=issues)


def _fallback_html(*, title: str, issues: list[str]) -> str:
    issue_items = "".join(f"<li>{escape(issue)}</li>" for issue in issues)
    if not issue_items:
        issue_items = "<li>Preview renderer did not return HTML.</li>"
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:24px;color:#111827}"
        "h1{font-size:20px}li{margin:8px 0}</style></head><body>"
        f"<h1>{escape(title)}</h1><ul>{issue_items}</ul></body></html>"
    )


def finding_source_citations(finding: ContractReviewFinding) -> list[str]:
    return [
        source.citation or source.source_id
        for source in finding.sources
        if source.citation or source.source_id
    ]
