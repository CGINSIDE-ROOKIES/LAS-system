from __future__ import annotations

import base64
from collections import defaultdict
from html import escape
import re

from pydantic import BaseModel, Field, model_validator

from document_processor import DocIR, ImageIR, PageInfo, ParagraphIR, RunIR, TableCellIR, TableIR
from document_processor.style_types import CellStyleInfo, ParaStyleInfo, RunStyleInfo


class AnnotationValidationError(ValueError):
    pass


class Annotation(BaseModel):
    target_unit_id: str
    start: int | None = None
    end: int | None = None
    label: str
    color: str = "#FFFF00"
    note: str = ""

    @model_validator(mode="after")
    def _validate_bounds(self) -> "Annotation":
        if self.start is not None and self.start < 0:
            raise ValueError("Annotation.start must be >= 0.")
        if self.end is not None and self.end < 0:
            raise ValueError("Annotation.end must be >= 0.")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("Annotation.end must be greater than Annotation.start.")
        return self


class ResolvedAnnotation(BaseModel):
    target_unit_id: str
    target_kind: str
    start: int
    end: int
    label: str
    color: str = "#FFFF00"
    note: str = ""
    resolved_text: str


def _iter_paragraphs(paragraphs: list[ParagraphIR]):
    for paragraph in paragraphs:
        yield paragraph
        for table in paragraph.tables:
            yield from _iter_table_paragraphs(table)


def _iter_table_paragraphs(table: TableIR):
    for cell in table.cells:
        for paragraph in cell.paragraphs:
            yield paragraph
            for nested_table in paragraph.tables:
                yield from _iter_table_paragraphs(nested_table)


def _paragraph_plain_text(paragraph: ParagraphIR) -> str:
    return "".join(run.text for run in paragraph.runs)


def _resolve_annotation_target(
    doc: DocIR,
    annotation: Annotation,
) -> ResolvedAnnotation:
    paragraph_map = {paragraph.unit_id: paragraph for paragraph in _iter_paragraphs(doc.paragraphs)}
    run_map = {
        run.unit_id: run
        for paragraph in paragraph_map.values()
        for run in paragraph.runs
    }

    if annotation.target_unit_id in run_map:
        run = run_map[annotation.target_unit_id]
        text = run.text
        start = annotation.start if annotation.start is not None else 0
        end = annotation.end if annotation.end is not None else len(text)
        if end > len(text):
            raise AnnotationValidationError(
                f"Annotation range {start}:{end} exceeds run length for {annotation.target_unit_id}."
            )
        return ResolvedAnnotation(
            target_unit_id=annotation.target_unit_id,
            target_kind="run",
            start=start,
            end=end,
            label=annotation.label,
            color=annotation.color,
            note=annotation.note,
            resolved_text=text[start:end],
        )

    if annotation.target_unit_id in paragraph_map:
        paragraph = paragraph_map[annotation.target_unit_id]
        if paragraph.tables or paragraph.images:
            raise AnnotationValidationError(
                f"Paragraph annotations do not support tables/images yet: {annotation.target_unit_id}."
            )
        text = _paragraph_plain_text(paragraph)
        start = annotation.start if annotation.start is not None else 0
        end = annotation.end if annotation.end is not None else len(text)
        if end > len(text):
            raise AnnotationValidationError(
                f"Annotation range {start}:{end} exceeds paragraph length for {annotation.target_unit_id}."
            )
        return ResolvedAnnotation(
            target_unit_id=annotation.target_unit_id,
            target_kind="paragraph",
            start=start,
            end=end,
            label=annotation.label,
            color=annotation.color,
            note=annotation.note,
            resolved_text=text[start:end],
        )

    raise AnnotationValidationError(f"Annotation target does not exist in DocIR: {annotation.target_unit_id}")


def resolve_annotations(
    doc: DocIR,
    annotations: list[Annotation],
) -> list[ResolvedAnnotation]:
    return [_resolve_annotation_target(doc, annotation) for annotation in annotations]


def _run_css(style: RunStyleInfo) -> str:
    parts: list[str] = []
    if style.color:
        parts.append(f"color:{style.color}")
    if style.size_pt:
        parts.append(f"font-size:{style.size_pt:.1f}pt")
    if style.highlight:
        parts.append(f"background-color:{style.highlight}")

    decorations = []
    if style.underline:
        decorations.append("underline")
    if style.strikethrough:
        decorations.append("line-through")
    if decorations:
        parts.append(f"text-decoration:{' '.join(decorations)}")

    return ";".join(parts)


def _style_wrap(html: str, style: RunStyleInfo | None) -> str:
    if style is None:
        return html

    if style.superscript:
        html = f"<sup>{html}</sup>"
    elif style.subscript:
        html = f"<sub>{html}</sub>"
    if style.bold:
        html = f"<b>{html}</b>"
    if style.italic:
        html = f"<i>{html}</i>"

    css = _run_css(style)
    if css:
        html = f'<span style="{css}">{html}</span>'

    return html


def _escape_whitespace(html: str) -> str:
    html = html.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    html = re.sub(r"  +", lambda match: "&nbsp;" * len(match.group(0)), html)
    return html


def _apply_annotations(
    text: str,
    annotations: list[ResolvedAnnotation],
) -> str:
    if not annotations:
        return escape(text)

    breakpoints = sorted({0, len(text)} | {item.start for item in annotations} | {item.end for item in annotations})
    fragments: list[str] = []

    for index in range(len(breakpoints) - 1):
        start = breakpoints[index]
        end = breakpoints[index + 1]
        segment = text[start:end]
        if not segment:
            continue

        active = [item for item in annotations if item.start <= start and item.end >= end]
        escaped_segment = escape(segment)
        if not active:
            fragments.append(escaped_segment)
            continue

        color = active[0].color
        label = " | ".join(item.label for item in active if item.label)
        note = " | ".join(item.note for item in active if item.note)
        attrs = [f'style="background-color:{escape(color)};padding:1px 2px;border-radius:2px"']
        if label:
            attrs.append(f'data-label="{escape(label)}"')
        if note:
            attrs.append(f'data-note="{escape(note)}"')
        title = " | ".join(part for part in (label, note) if part)
        if title:
            attrs.append(f'title="{escape(title)}"')
        fragments.append(f"<mark {' '.join(attrs)}>{escaped_segment}</mark>")

    return "".join(fragments)


def _wrap_run_with_annotations(run: RunIR, annotations: list[ResolvedAnnotation]) -> str:
    html = _apply_annotations(run.text, annotations)
    if not html:
        return ""
    html = _escape_whitespace(html)
    html = _style_wrap(html, run.run_style)
    return f'<span data-unit-id="{escape(run.unit_id)}">{html}</span>'


def _render_image(doc_ir: DocIR, image: ImageIR) -> str:
    asset = doc_ir.assets.get(image.image_id)
    if asset is None:
        return ""

    style_parts = ["max-width:100%", "vertical-align:middle"]
    if image.display_width_pt is not None:
        style_parts.append(f"width:{image.display_width_pt:.1f}pt")
    if image.display_height_pt is not None:
        style_parts.append(f"height:{image.display_height_pt:.1f}pt")
    elif image.display_width_pt is None:
        style_parts.append("height:auto")

    attrs = [
        f'src="{escape(asset.as_data_url(), quote=True)}"',
        f'alt="{escape(image.alt_text or asset.filename or "")}"',
        f'style="{";".join(style_parts)}"',
    ]
    return f"<img {' '.join(attrs)} />"


def _paragraph_css(style: ParaStyleInfo | None, *, clamp_negative_first_line_indent: bool = False) -> str:
    parts: list[str] = ["margin:0"]
    if style is not None:
        if style.align:
            parts.append(f"text-align:{style.align}")
        if style.left_indent_pt is not None:
            parts.append(f"padding-left:{style.left_indent_pt:.1f}pt")
        if style.right_indent_pt is not None:
            parts.append(f"padding-right:{style.right_indent_pt:.1f}pt")
        if style.first_line_indent_pt is not None:
            text_indent = style.first_line_indent_pt
            if clamp_negative_first_line_indent and text_indent < 0:
                text_indent = 0.0
            parts.append(f"text-indent:{text_indent:.1f}pt")
    return ";".join(parts)


def _flush_paragraph(
    paragraph_unit_id: str,
    fragments: list[str],
    para_style: ParaStyleInfo | None,
    *,
    clamp_negative_first_line_indent: bool = False,
) -> str:
    content = "".join(fragments)
    if not content.strip():
        content = "&nbsp;"
    return (
        f'<p data-unit-id="{escape(paragraph_unit_id)}" '
        f'style="{_paragraph_css(para_style, clamp_negative_first_line_indent=clamp_negative_first_line_indent)}">'
        f"{content}</p>"
    )


def _parse_border_css(border_css: str | None) -> tuple[int, str, str] | None:
    if not border_css:
        return None
    match = re.fullmatch(r"\s*(\d+)px\s+([a-zA-Z-]+)\s+(#[0-9A-Fa-f]{3,8})\s*", border_css)
    if not match:
        return None
    return int(match.group(1)), match.group(2), match.group(3)


def _svg_dasharray(style_name: str, stroke_width: int) -> str | None:
    if style_name == "dashed":
        return f"{max(stroke_width * 4, 4)} {max(stroke_width * 2, 2)}"
    if style_name == "dotted":
        return f"{max(stroke_width, 1)} {max(stroke_width * 2, 2)}"
    return None


def _svg_diagonal_lines(style: CellStyleInfo) -> str | None:
    diagonals: list[tuple[str, int, str, str]] = []
    for direction, border_css in (
        ("tl_br", style.diagonal_tl_br),
        ("tr_bl", style.diagonal_tr_bl),
    ):
        parsed = _parse_border_css(border_css)
        if parsed is None:
            continue
        stroke_width, style_name, color = parsed
        diagonals.append((direction, stroke_width, style_name, color))

    if not diagonals:
        return None

    svg_parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none">']
    for direction, stroke_width, style_name, color in diagonals:
        dasharray = _svg_dasharray(style_name, stroke_width)
        if direction == "tl_br":
            coords = (0, 0, 100, 100)
        else:
            coords = (100, 0, 0, 100)

        attrs = [
            f'x1="{coords[0]}"',
            f'y1="{coords[1]}"',
            f'x2="{coords[2]}"',
            f'y2="{coords[3]}"',
            f'stroke="{color}"',
            f'stroke-width="{stroke_width}"',
        ]
        if dasharray:
            attrs.append(f'stroke-dasharray="{dasharray}"')
        svg_parts.append(f"<line {' '.join(attrs)} />")
    svg_parts.append("</svg>")
    return "".join(svg_parts)


def _cell_diagonal_background(style: CellStyleInfo) -> str | None:
    svg = _svg_diagonal_lines(style)
    if svg is None:
        return None
    svg_base64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{svg_base64}"


def _cell_css(style: CellStyleInfo | None) -> str:
    parts: list[str] = []
    if style is not None:
        if style.background:
            parts.append(f"background-color:{style.background}")
        if style.vertical_align:
            parts.append(f"vertical-align:{style.vertical_align}")
        if style.horizontal_align:
            parts.append(f"text-align:{style.horizontal_align}")
        if style.width_pt is not None:
            parts.append(f"width:{style.width_pt:.1f}pt")
        if style.height_pt is not None:
            parts.append(f"height:{style.height_pt:.1f}pt")
        parts.append(f"border-top:{style.border_top or 'none'}")
        parts.append(f"border-bottom:{style.border_bottom or 'none'}")
        parts.append(f"border-left:{style.border_left or 'none'}")
        parts.append(f"border-right:{style.border_right or 'none'}")
        diagonal_background = _cell_diagonal_background(style)
        if diagonal_background:
            parts.append(f"background-image:url({diagonal_background})")
            parts.append("background-repeat:no-repeat")
            parts.append("background-size:100% 100%")
    else:
        parts.extend(
            [
                "border-top:none",
                "border-bottom:none",
                "border-left:none",
                "border-right:none",
            ]
        )
    parts.append("padding:4px 6px")
    return ";".join(parts)


def _table_css(table: TableIR, para_style: ParaStyleInfo | None) -> str:
    align = para_style.align if para_style is not None else None
    parts = ["border-collapse:collapse", "margin-top:8px", "margin-bottom:12px"]
    if table.table_style is not None and table.table_style.width_pt is not None:
        parts.append(f"width:{table.table_style.width_pt:.1f}pt")
    if table.table_style is not None and table.table_style.height_pt is not None:
        parts.append(f"height:{table.table_style.height_pt:.1f}pt")
    if align == "center":
        parts.extend(["margin-left:auto", "margin-right:auto"])
    elif align == "right":
        parts.extend(["margin-left:auto", "margin-right:0"])
    else:
        parts.extend(["margin-left:0", "margin-right:auto"])
    return ";".join(parts)


def _run_annotations_for_segment(
    run: RunIR,
    run_annotations_by_id: dict[str, list[ResolvedAnnotation]],
    paragraph_annotations: list[ResolvedAnnotation],
    paragraph_cursor: int,
) -> list[ResolvedAnnotation]:
    resolved: list[ResolvedAnnotation] = []
    for item in run_annotations_by_id.get(run.unit_id, []):
        resolved.append(item)

    run_start = paragraph_cursor
    run_end = paragraph_cursor + len(run.text)
    for item in paragraph_annotations:
        if item.end <= run_start or item.start >= run_end:
            continue
        local_start = max(0, item.start - run_start)
        local_end = min(len(run.text), item.end - run_start)
        if local_start >= local_end:
            continue
        resolved.append(
            ResolvedAnnotation(
                target_unit_id=run.unit_id,
                target_kind="run_segment",
                start=local_start,
                end=local_end,
                label=item.label,
                color=item.color,
                note=item.note,
                resolved_text=run.text[local_start:local_end],
            )
        )
    return resolved


def _render_paragraph_like(
    doc_ir: DocIR,
    paragraph: ParagraphIR,
    paragraph_annotations: list[ResolvedAnnotation],
    paragraph_annotations_by_id: dict[str, list[ResolvedAnnotation]],
    run_annotations_by_id: dict[str, list[ResolvedAnnotation]],
    *,
    clamp_negative_first_line_indent: bool = False,
) -> str:
    parts: list[str] = []
    inline_fragments: list[str] = []
    paragraph_cursor = 0

    for node in paragraph.content:
        if isinstance(node, RunIR):
            annotations = _run_annotations_for_segment(
                node,
                run_annotations_by_id,
                paragraph_annotations,
                paragraph_cursor,
            )
            inline_fragments.append(_wrap_run_with_annotations(node, annotations))
            paragraph_cursor += len(node.text)
            continue

        if isinstance(node, ImageIR):
            image_html = _render_image(doc_ir, node)
            if image_html:
                inline_fragments.append(image_html)
            continue

        if isinstance(node, TableIR):
            if inline_fragments:
                parts.append(
                    _flush_paragraph(
                        paragraph.unit_id,
                        inline_fragments,
                        paragraph.para_style,
                        clamp_negative_first_line_indent=clamp_negative_first_line_indent,
                    )
                )
                inline_fragments = []
            parts.append(
                _render_table(
                    doc_ir,
                    node,
                    run_annotations_by_id,
                    para_style=paragraph.para_style,
                    paragraph_annotations_by_id=paragraph_annotations_by_id,
                )
            )

    if inline_fragments:
        parts.append(
            _flush_paragraph(
                paragraph.unit_id,
                inline_fragments,
                paragraph.para_style,
                clamp_negative_first_line_indent=clamp_negative_first_line_indent,
            )
        )
    elif not parts:
        parts.append(
            _flush_paragraph(
                paragraph.unit_id,
                [],
                paragraph.para_style,
                clamp_negative_first_line_indent=clamp_negative_first_line_indent,
            )
        )

    return "\n".join(parts)


def _render_cell_paragraph(
    doc_ir: DocIR,
    paragraph: ParagraphIR,
    paragraph_annotations_by_id: dict[str, list[ResolvedAnnotation]],
    run_annotations_by_id: dict[str, list[ResolvedAnnotation]],
) -> str:
    return _render_paragraph_like(
        doc_ir,
        paragraph,
        paragraph_annotations_by_id.get(paragraph.unit_id, []),
        paragraph_annotations_by_id,
        run_annotations_by_id,
        clamp_negative_first_line_indent=True,
    )


def _render_cell(
    doc_ir: DocIR,
    cell: TableCellIR,
    paragraph_annotations_by_id: dict[str, list[ResolvedAnnotation]],
    run_annotations_by_id: dict[str, list[ResolvedAnnotation]],
) -> str:
    attrs = [
        f'data-unit-id="{escape(cell.unit_id)}"',
        f'style="{_cell_css(cell.cell_style)}"',
    ]
    if cell.cell_style is not None:
        if cell.cell_style.colspan > 1:
            attrs.append(f'colspan="{cell.cell_style.colspan}"')
        if cell.cell_style.rowspan > 1:
            attrs.append(f'rowspan="{cell.cell_style.rowspan}"')

    if cell.paragraphs:
        content = "".join(
            _render_cell_paragraph(doc_ir, paragraph, paragraph_annotations_by_id, run_annotations_by_id)
            for paragraph in cell.paragraphs
        )
    else:
        content = "&nbsp;"

    return f"<td {' '.join(attrs)}>{content}</td>"


def _render_table(
    doc_ir: DocIR,
    table: TableIR,
    run_annotations_by_id: dict[str, list[ResolvedAnnotation]],
    *,
    para_style: ParaStyleInfo | None = None,
    paragraph_annotations_by_id: dict[str, list[ResolvedAnnotation]] | None = None,
) -> str:
    paragraph_annotations_by_id = paragraph_annotations_by_id or {}
    if not table.cells:
        return f'<table data-unit-id="{escape(table.unit_id)}" style="{_table_css(table, para_style)}"></table>'

    covered: set[tuple[int, int]] = set()
    cells_by_pos = {(cell.row_index, cell.col_index): cell for cell in table.cells}
    max_row = max(cell.row_index for cell in table.cells)
    max_col = max(cell.col_index for cell in table.cells)

    lines = [f'<table data-unit-id="{escape(table.unit_id)}" style="{_table_css(table, para_style)}">']
    for row in range(1, max_row + 1):
        lines.append("  <tr>")
        for col in range(1, max_col + 1):
            if (row, col) in covered:
                continue

            cell = cells_by_pos.get((row, col))
            if cell is None:
                lines.append('    <td style="padding:4px 6px;border:none">&nbsp;</td>')
                continue

            rowspan = max(cell.cell_style.rowspan, 1) if cell.cell_style is not None else 1
            colspan = max(cell.cell_style.colspan, 1) if cell.cell_style is not None else 1

            for covered_row in range(row, row + rowspan):
                for covered_col in range(col, col + colspan):
                    if covered_row == row and covered_col == col:
                        continue
                    covered.add((covered_row, covered_col))

            lines.append(
                "    "
                + _render_cell(
                    doc_ir,
                    cell,
                    paragraph_annotations_by_id,
                    run_annotations_by_id,
                )
            )
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _page_style(page: PageInfo) -> str:
    parts = [
        "box-sizing:border-box",
        "background:#fff",
        "border:1px solid #222",
        "box-shadow:0 1px 3px rgba(0,0,0,0.08)",
        "margin:0 auto 24px auto",
    ]
    if page.width_pt is not None:
        parts.append(f"width:{page.width_pt:.1f}pt")
    else:
        parts.append("max-width:900px")
    if page.height_pt is not None:
        parts.append(f"min-height:{page.height_pt:.1f}pt")
    return ";".join(parts)


def _page_content_style(page: PageInfo) -> str:
    margin_top = page.margin_top_pt if page.margin_top_pt is not None else 48.0
    margin_right = page.margin_right_pt if page.margin_right_pt is not None else 42.0
    margin_bottom = page.margin_bottom_pt if page.margin_bottom_pt is not None else 48.0
    margin_left = page.margin_left_pt if page.margin_left_pt is not None else 42.0
    return (
        "box-sizing:border-box;"
        f"padding:{margin_top:.1f}pt {margin_right:.1f}pt {margin_bottom:.1f}pt {margin_left:.1f}pt"
    )


def _render_paragraph(
    doc_ir: DocIR,
    paragraph: ParagraphIR,
    paragraph_annotations_by_id: dict[str, list[ResolvedAnnotation]],
    run_annotations_by_id: dict[str, list[ResolvedAnnotation]],
) -> str:
    return _render_paragraph_like(
        doc_ir,
        paragraph,
        paragraph_annotations_by_id.get(paragraph.unit_id, []),
        paragraph_annotations_by_id,
        run_annotations_by_id,
    )


def _render_paged_body(
    doc_ir: DocIR,
    paragraph_annotations_by_id: dict[str, list[ResolvedAnnotation]],
    run_annotations_by_id: dict[str, list[ResolvedAnnotation]],
) -> str:
    paragraphs_by_page: dict[int, list[ParagraphIR]] = defaultdict(list)
    unpaged: list[ParagraphIR] = []

    for paragraph in doc_ir.paragraphs:
        if paragraph.page_number is None:
            unpaged.append(paragraph)
            continue
        paragraphs_by_page[paragraph.page_number].append(paragraph)

    parts: list[str] = []
    for page in doc_ir.pages:
        page_paragraphs = paragraphs_by_page.get(page.page_number, [])
        content_html = "\n\n".join(
            _render_paragraph(doc_ir, paragraph, paragraph_annotations_by_id, run_annotations_by_id)
            for paragraph in page_paragraphs
        )
        parts.append(
            f'<section class="document-page" data-page-number="{page.page_number}" style="{_page_style(page)}">'
            f'<div class="document-page__content" style="{_page_content_style(page)}">{content_html or "&nbsp;"}</div>'
            "</section>"
        )

    if unpaged:
        parts.append(
            '<section class="document-unpaged">'
            + "\n\n".join(
                _render_paragraph(doc_ir, paragraph, paragraph_annotations_by_id, run_annotations_by_id)
                for paragraph in unpaged
            )
            + "</section>"
        )

    return "\n".join(parts)


def render_annotated_html(
    doc: DocIR,
    annotations: list[Annotation],
    *,
    title: str | None = None,
) -> str:
    resolved = resolve_annotations(doc, annotations)
    paragraph_annotations_by_id: dict[str, list[ResolvedAnnotation]] = defaultdict(list)
    run_annotations_by_id: dict[str, list[ResolvedAnnotation]] = defaultdict(list)
    for item in resolved:
        if item.target_kind == "paragraph":
            paragraph_annotations_by_id[item.target_unit_id].append(item)
        else:
            run_annotations_by_id[item.target_unit_id].append(item)

    body = (
        _render_paged_body(doc, paragraph_annotations_by_id, run_annotations_by_id)
        if doc.pages
        else "\n\n".join(
            _render_paragraph(doc, paragraph, paragraph_annotations_by_id, run_annotations_by_id)
            for paragraph in doc.paragraphs
        )
    )
    resolved_title = title or doc.doc_id or "Document Review"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(resolved_title)}</title>
<style>
  body {{
    max-width: 1100px;
    margin: 2em auto;
    padding: 0 1rem;
    line-height: 1.6;
    color: #1a1a1a;
    font-family: serif;
    background:#f5f5f2;
  }}
  p {{
    margin: 0 0 0.45em 0;
  }}
  table {{
    border-collapse: collapse;
    margin: 8px 0 12px 0;
  }}
  img {{
    max-width: 100%;
    height: auto;
  }}
  mark {{
    cursor: help;
  }}
  .document-unpaged {{
    max-width: 900px;
    margin: 0 auto;
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


__all__ = [
    "Annotation",
    "AnnotationValidationError",
    "ResolvedAnnotation",
    "render_annotated_html",
    "resolve_annotations",
]
