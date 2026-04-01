"""Unified style extraction for HWP/HWPX/DOCX documents.

Returns a `StyleMap` keyed by the same structural unit IDs used by
structured mapping exporters.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree as ET
import zipfile

from processor_types import (
    CellStyleInfo,
    ParaStyleInfo,
    RunStyleInfo,
    StyleMap,
    TableStyleInfo,
)

from .hwp_converter import convert_hwp_to_hwpx_bytes

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument
    from hwpx import HwpxDocument


DocType = Literal["auto", "hwp", "hwpx", "docx"]

_NS_HH = "http://www.hancom.co.kr/hwpml/2011/head"
_NS_HC = "http://www.hancom.co.kr/hwpml/2011/core"
_NS_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = f"{{{_NS_HP}}}"

# HWPML defines 10pt == 1000 hwpunit.
_HWPUNIT_PER_PT = 100.0

_HWPX_BORDER_STYLE = {
    "SOLID": "solid",
    "DASH": "dashed",
    "DOT": "dotted",
    "DASH_DOT": "dashed",
    "DASH_DOT_DOT": "dotted",
    "DOUBLE": "double",
    "NONE": "none",
}

_HWPX_HALIGN = {
    "LEFT": "left",
    "CENTER": "center",
    "RIGHT": "right",
    "JUSTIFY": "justify",
    "DISTRIBUTE": "justify",
}

_HWPX_VALIGN = {
    "TOP": "top",
    "CENTER": "center",
    "BOTTOM": "bottom",
    "BASELINE": "top",
}

_DOCX_ALIGN = {0: "left", 1: "center", 2: "right", 3: "justify"}


def _has_para_style(info: ParaStyleInfo) -> bool:
    return any(
        value is not None
        for value in (
            info.align,
            info.left_indent_pt,
            info.right_indent_pt,
            info.first_line_indent_pt,
            info.hanging_indent_pt,
        )
    )


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _length_to_pt(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / 12700.0
    except (TypeError, ValueError):
        return None


def _hwp_margin_value_to_pt(el: ET.Element | None) -> float | None:
    if el is None:
        return None

    raw = el.get("value")
    if raw is None:
        return None

    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None

    unit = (el.get("unit") or "HWPUNIT").upper()
    if unit == "HWPUNIT":
        return number / _HWPUNIT_PER_PT
    if unit == "PT":
        return number
    return number


def _hwpx_border_css(border_el: ET.Element | None) -> str | None:
    if border_el is None:
        return None
    btype = border_el.get("type", "NONE")
    if btype == "NONE":
        return None
    width = border_el.get("width", "0.12 mm")
    try:
        mm_val = float(width.replace("mm", "").strip())
        px = max(1, round(mm_val * 3.78))
    except (ValueError, AttributeError):
        px = 1
    color = border_el.get("color", "#000000")
    style = _HWPX_BORDER_STYLE.get(btype, "solid")
    return f"{px}px {style} {color}"


def _map_by_id(root: ET.Element | None, tag: str) -> dict[str, ET.Element]:
    if root is None:
        return {}
    out: dict[str, ET.Element] = {}
    for el in root.findall(f".//{{{_NS_HH}}}{tag}"):
        el_id = el.get("id")
        if el_id:
            out[el_id] = el
    return out


def _hwpx_para_style_from_pr(para_pr_el: ET.Element | None) -> ParaStyleInfo | None:
    if para_pr_el is None:
        return None

    info = ParaStyleInfo()

    align_el = para_pr_el.find(f"{{{_NS_HH}}}align")
    if align_el is not None:
        info.align = _HWPX_HALIGN.get(align_el.get("horizontal", ""))

    margin_el = para_pr_el.find(f"{{{_NS_HH}}}margin")
    if margin_el is None:
        margin_el = para_pr_el.find(f".//{{{_NS_HH}}}margin")
    if margin_el is not None:
        first_line = _hwp_margin_value_to_pt(margin_el.find(f"{{{_NS_HC}}}intent"))
        info.first_line_indent_pt = first_line
        info.left_indent_pt = _hwp_margin_value_to_pt(margin_el.find(f"{{{_NS_HC}}}left"))
        info.right_indent_pt = _hwp_margin_value_to_pt(margin_el.find(f"{{{_NS_HC}}}right"))
        if first_line is not None and first_line < 0:
            info.hanging_indent_pt = abs(first_line)

    return info if _has_para_style(info) else None


def _hwpx_run_style_from_char_pr(char_pr_el: ET.Element | None) -> RunStyleInfo:
    info = RunStyleInfo()
    if char_pr_el is None:
        return info

    info.bold = char_pr_el.find(f"{{{_NS_HH}}}bold") is not None
    info.italic = char_pr_el.find(f"{{{_NS_HH}}}italic") is not None

    underline_el = char_pr_el.find(f"{{{_NS_HH}}}underline")
    if underline_el is not None and underline_el.get("type", "NONE") != "NONE":
        info.underline = True

    strike_el = char_pr_el.find(f"{{{_NS_HH}}}strikeout")
    if strike_el is not None and strike_el.get("shape", "NONE") != "NONE":
        info.strikethrough = True

    color = char_pr_el.get("textColor")
    if color and color != "#000000":
        info.color = color

    height = char_pr_el.get("height")
    if height is not None:
        try:
            info.size_pt = int(height) / 100.0
        except (TypeError, ValueError):
            pass

    return info


def _hwpx_cell_style(
    cell_el: ET.Element,
    *,
    para_pr_map: dict[str, ET.Element],
    border_fill_map: dict[str, ET.Element],
) -> CellStyleInfo:
    info = CellStyleInfo()

    span_el = cell_el.find(f"{_HP}cellSpan")
    if span_el is not None:
        info.rowspan = _safe_int(span_el.get("rowSpan")) or 1
        info.colspan = _safe_int(span_el.get("colSpan")) or 1

    sub_list = cell_el.find(f"{_HP}subList")
    if sub_list is not None:
        valign = sub_list.get("vertAlign", "")
        info.vertical_align = _HWPX_VALIGN.get(valign)

    cell_paragraphs = _iter_cell_paragraphs(cell_el)
    if cell_paragraphs:
        first_para = cell_paragraphs[0]
        pp_ref = first_para.get("paraPrIDRef")
        if pp_ref and pp_ref in para_pr_map:
            pstyle = _hwpx_para_style_from_pr(para_pr_map[pp_ref])
            if pstyle and pstyle.align:
                info.horizontal_align = pstyle.align

    bf_ref = cell_el.get("borderFillIDRef")
    if bf_ref and bf_ref in border_fill_map:
        border_fill = border_fill_map[bf_ref]
        info.border_top = _hwpx_border_css(border_fill.find(f"{{{_NS_HH}}}topBorder"))
        info.border_bottom = _hwpx_border_css(border_fill.find(f"{{{_NS_HH}}}bottomBorder"))
        info.border_left = _hwpx_border_css(border_fill.find(f"{{{_NS_HH}}}leftBorder"))
        info.border_right = _hwpx_border_css(border_fill.find(f"{{{_NS_HH}}}rightBorder"))

        fill_brush = border_fill.find(f"{{{_NS_HH}}}fillBrush")
        if fill_brush is None:
            fill_brush = border_fill.find(f"{{{_NS_HC}}}fillBrush")
        if fill_brush is not None:
            face_color = fill_brush.get("faceColor")
            if not face_color:
                win_brush = fill_brush.find(f"{{{_NS_HH}}}winBrush")
                if win_brush is None:
                    win_brush = fill_brush.find(f"{{{_NS_HC}}}winBrush")
                if win_brush is not None:
                    face_color = win_brush.get("faceColor")
            if face_color and face_color.lower() not in ("none", "#ffffff", "transparent"):
                info.background = face_color

    return info


def _iter_section_paragraphs(section_root: ET.Element) -> list[ET.Element]:
    return section_root.findall(f"{_HP}p")


def _iter_paragraph_tables(paragraph_el: ET.Element) -> list[ET.Element]:
    return paragraph_el.findall(f"{_HP}run/{_HP}tbl")


def _iter_cell_paragraphs(cell_el: ET.Element) -> list[ET.Element]:
    direct = cell_el.findall(f"{_HP}subList/{_HP}p")
    if direct:
        return direct
    return cell_el.findall(f".//{_HP}p")


def _section_roots_from_bytes(source: bytes) -> list[ET.Element]:
    section_name_pattern = re.compile(r"^Contents/section\d+\.xml$")

    with zipfile.ZipFile(BytesIO(source)) as zf:
        def _section_order(name: str) -> int:
            match = re.search(r"section(\d+)\.xml$", name)
            return int(match.group(1)) if match else -1

        names = sorted(
            (name for name in zf.namelist() if section_name_pattern.match(name)),
            key=_section_order,
        )
        return [ET.fromstring(zf.read(name)) for name in names]


def _header_root_from_bytes(source: bytes) -> ET.Element | None:
    with zipfile.ZipFile(BytesIO(source)) as zf:
        try:
            return ET.fromstring(zf.read("Contents/header.xml"))
        except KeyError:
            return None


def _extract_styles_hwpx_from_roots(
    section_roots: list[ET.Element],
    *,
    header_root: ET.Element | None,
) -> StyleMap:
    style_map = StyleMap()

    para_pr_map = _map_by_id(header_root, "paraPr")
    char_pr_map = _map_by_id(header_root, "charPr")
    border_fill_map = _map_by_id(header_root, "borderFill")

    for s_idx, section_root in enumerate(section_roots, start=1):
        for p_idx, para_el in enumerate(_iter_section_paragraphs(section_root), start=1):
            paragraph_id = f"s{s_idx}.p{p_idx}"

            para_pr_ref = para_el.get("paraPrIDRef")
            if para_pr_ref and para_pr_ref in para_pr_map:
                para_style = _hwpx_para_style_from_pr(para_pr_map[para_pr_ref])
                if para_style is not None:
                    style_map.paragraphs[paragraph_id] = para_style

            run_els = para_el.findall(f"{_HP}run")
            if not run_els:
                style_map.runs[f"{paragraph_id}.r1"] = RunStyleInfo()
            else:
                for r_idx, run_el in enumerate(run_els, start=1):
                    char_pr_ref = run_el.get("charPrIDRef")
                    char_pr_el = char_pr_map.get(char_pr_ref) if char_pr_ref else None
                    style_map.runs[f"{paragraph_id}.r{r_idx}"] = _hwpx_run_style_from_char_pr(
                        char_pr_el
                    )

            for t_idx, table_el in enumerate(_iter_paragraph_tables(para_el), start=1):
                table_id = f"{paragraph_id}.r1.tbl{t_idx}"
                row_els = table_el.findall(f"{_HP}tr")
                style_map.tables[table_id] = TableStyleInfo(
                    row_count=len(row_els),
                    col_count=max((len(row.findall(f'{_HP}tc')) for row in row_els), default=0),
                )

                for tr_idx, row_el in enumerate(row_els, start=1):
                    for tc_idx, cell_el in enumerate(row_el.findall(f"{_HP}tc"), start=1):
                        cell_id = f"{table_id}.tr{tr_idx}.tc{tc_idx}"
                        style_map.cells[cell_id] = _hwpx_cell_style(
                            cell_el,
                            para_pr_map=para_pr_map,
                            border_fill_map=border_fill_map,
                        )

                        cell_paragraphs = _iter_cell_paragraphs(cell_el)
                        if not cell_paragraphs:
                            run_id = f"{cell_id}.p1.r1"
                            style_map.runs[run_id] = RunStyleInfo()
                            continue

                        for cp_idx, cell_para_el in enumerate(cell_paragraphs, start=1):
                            cell_paragraph_id = f"{cell_id}.p{cp_idx}"
                            cell_para_pr_ref = cell_para_el.get("paraPrIDRef")
                            if cell_para_pr_ref and cell_para_pr_ref in para_pr_map:
                                cp_style = _hwpx_para_style_from_pr(para_pr_map[cell_para_pr_ref])
                                if cp_style is not None:
                                    style_map.paragraphs[cell_paragraph_id] = cp_style

                            cell_run_els = cell_para_el.findall(f"{_HP}run")
                            if not cell_run_els:
                                style_map.runs[f"{cell_paragraph_id}.r1"] = RunStyleInfo()
                                continue

                            for cr_idx, cell_run_el in enumerate(cell_run_els, start=1):
                                char_pr_ref = cell_run_el.get("charPrIDRef")
                                char_pr_el = char_pr_map.get(char_pr_ref) if char_pr_ref else None
                                style_map.runs[f"{cell_paragraph_id}.r{cr_idx}"] = (
                                    _hwpx_run_style_from_char_pr(char_pr_el)
                                )

    return style_map


def extract_styles_hwpx(source: "HwpxDocument | str | Path | bytes") -> StyleMap:
    """Extract style map from HWPX source."""
    if isinstance(source, bytes):
        return _extract_styles_hwpx_from_roots(
            _section_roots_from_bytes(source),
            header_root=_header_root_from_bytes(source),
        )

    if isinstance(source, (str, Path)):
        return extract_styles_hwpx(Path(source).read_bytes())

    # Optional runtime support for already-open HwpxDocument.
    try:
        from hwpx import HwpxDocument
    except ImportError:
        HwpxDocument = None

    if HwpxDocument is not None and isinstance(source, HwpxDocument):
        section_roots = [section.element for section in source.sections]
        header_root = source.headers[0].element if source.headers else None
        return _extract_styles_hwpx_from_roots(section_roots, header_root=header_root)

    raise TypeError(
        "source must be HwpxDocument, bytes, or a .hwpx path, "
        f"got {type(source)!r}"
    )


def _docx_run_style(run) -> RunStyleInfo:
    info = RunStyleInfo(
        bold=bool(run.bold),
        italic=bool(run.italic),
        underline=bool(run.underline),
    )

    font = run.font

    if font.color and font.color.rgb:
        rgb = str(font.color.rgb)
        if rgb != "000000":
            info.color = f"#{rgb}"

    if font.size is not None:
        info.size_pt = _length_to_pt(font.size)

    if font.strike:
        info.strikethrough = True
    if font.superscript:
        info.superscript = True
    if font.subscript:
        info.subscript = True
    if font.highlight_color is not None:
        info.highlight = str(font.highlight_color)

    return info


def _docx_para_style(paragraph) -> ParaStyleInfo | None:
    info = ParaStyleInfo()

    if paragraph.alignment is not None:
        info.align = _DOCX_ALIGN.get(paragraph.alignment)

    pf = paragraph.paragraph_format
    if pf is not None:
        info.left_indent_pt = _length_to_pt(pf.left_indent)
        info.right_indent_pt = _length_to_pt(pf.right_indent)

        first_line = _length_to_pt(pf.first_line_indent)
        info.first_line_indent_pt = first_line
        if first_line is not None and first_line < 0:
            info.hanging_indent_pt = abs(first_line)

    return info if _has_para_style(info) else None


def _docx_border_css(tc_borders, side: str) -> str | None:
    if tc_borders is None:
        return None

    from docx.oxml.ns import qn

    el = tc_borders.find(qn(f"w:{side}"))
    if el is None:
        return None
    val = el.get(qn("w:val"), "none")
    if val in ("none", "nil"):
        return None
    sz = el.get(qn("w:sz"), "4")
    try:
        px = max(1, round(int(sz) / 8 * 1.333))
    except (TypeError, ValueError):
        px = 1
    color = el.get(qn("w:color"), "000000")
    style_map = {"single": "solid", "double": "double", "dashed": "dashed", "dotted": "dotted"}
    css_style = style_map.get(val, "solid")
    return f"{px}px {css_style} #{color}"


def _docx_cell_style(cell) -> CellStyleInfo:
    from docx.oxml.ns import qn

    info = CellStyleInfo()
    tc = cell._tc
    tc_pr = tc.find(qn("w:tcPr"))
    if tc_pr is None:
        return info

    grid_span = tc_pr.find(qn("w:gridSpan"))
    if grid_span is not None:
        try:
            info.colspan = int(grid_span.get(qn("w:val"), "1"))
        except (TypeError, ValueError):
            pass

    v_align = tc_pr.find(qn("w:vAlign"))
    if v_align is not None:
        val = v_align.get(qn("w:val"), "")
        info.vertical_align = {"top": "top", "center": "center", "bottom": "bottom"}.get(val)

    if cell.paragraphs:
        pstyle = _docx_para_style(cell.paragraphs[0])
        if pstyle is not None and pstyle.align is not None:
            info.horizontal_align = pstyle.align

    shd = tc_pr.find(qn("w:shd"))
    if shd is not None:
        fill = shd.get(qn("w:fill"))
        if fill and fill.lower() not in ("auto", "ffffff", "none"):
            info.background = f"#{fill}"

    tc_borders = tc_pr.find(qn("w:tcBorders"))
    info.border_top = _docx_border_css(tc_borders, "top")
    info.border_bottom = _docx_border_css(tc_borders, "bottom")
    info.border_left = _docx_border_css(tc_borders, "left")
    info.border_right = _docx_border_css(tc_borders, "right")
    return info


def extract_styles_docx(
    source: "DocxDocument | str | Path",
    *,
    include_tables: bool = True,
) -> StyleMap:
    """Extract style map from DOCX source."""
    from docx import Document as load_docx
    from docx.document import Document as DocxDocument
    from docx.oxml.ns import qn
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    from .docx_structured_exporter import _iter_blocks

    doc = source if isinstance(source, DocxDocument) else load_docx(str(source))
    style_map = StyleMap()

    p_idx = 0
    tbl_counter = 0
    vmerge_starts: dict[tuple[str, int], str] = {}

    for block in _iter_blocks(
        doc,
        CT_P=CT_P,
        CT_Tbl=CT_Tbl,
        Paragraph=Paragraph,
        Table=Table,
    ):
        if isinstance(block, Paragraph):
            p_idx += 1
            paragraph_id = f"s1.p{p_idx}"

            pstyle = _docx_para_style(block)
            if pstyle is not None:
                style_map.paragraphs[paragraph_id] = pstyle

            if not block.runs:
                style_map.runs[f"{paragraph_id}.r1"] = RunStyleInfo()
            else:
                for r_idx, run in enumerate(block.runs, start=1):
                    style_map.runs[f"{paragraph_id}.r{r_idx}"] = _docx_run_style(run)
            continue

        if not include_tables or not isinstance(block, Table):
            continue

        tbl_counter += 1
        p_idx += 1
        table_id = f"s1.p{p_idx}.r1.tbl{tbl_counter}"
        style_map.tables[table_id] = TableStyleInfo(
            row_count=len(block.rows),
            col_count=len(block.columns),
        )

        for tr_idx, row in enumerate(block.rows, start=1):
            for tc_idx, cell in enumerate(row.cells, start=1):
                cell_id = f"{table_id}.tr{tr_idx}.tc{tc_idx}"

                tc_pr = cell._tc.find(qn("w:tcPr"))
                if tc_pr is not None:
                    v_merge = tc_pr.find(qn("w:vMerge"))
                    if v_merge is not None:
                        val = v_merge.get(qn("w:val"), "")
                        col_key = (table_id, tc_idx)
                        if val == "restart":
                            vmerge_starts[col_key] = cell_id
                        elif col_key in vmerge_starts:
                            start_cell_id = vmerge_starts[col_key]
                            start_style = style_map.cells.get(start_cell_id)
                            if start_style is not None:
                                start_style.rowspan += 1
                            continue
                    else:
                        vmerge_starts.pop((table_id, tc_idx), None)

                style_map.cells[cell_id] = _docx_cell_style(cell)

                if not cell.paragraphs:
                    style_map.runs[f"{cell_id}.p1.r1"] = RunStyleInfo()
                    continue

                for cp_idx, cell_para in enumerate(cell.paragraphs, start=1):
                    cell_paragraph_id = f"{cell_id}.p{cp_idx}"
                    cp_style = _docx_para_style(cell_para)
                    if cp_style is not None:
                        style_map.paragraphs[cell_paragraph_id] = cp_style

                    if not cell_para.runs:
                        style_map.runs[f"{cell_paragraph_id}.r1"] = RunStyleInfo()
                        continue

                    for cr_idx, cell_run in enumerate(cell_para.runs, start=1):
                        style_map.runs[f"{cell_paragraph_id}.r{cr_idx}"] = _docx_run_style(
                            cell_run
                        )

    return style_map


def _resolve_doc_type(source: object, doc_type: DocType) -> Literal["hwp", "hwpx", "docx"]:
    if doc_type in ("hwp", "hwpx", "docx"):
        return doc_type

    if isinstance(source, bytes):
        return "hwpx"

    if isinstance(source, (str, Path)):
        suffix = Path(source).suffix.lower()
        if suffix == ".hwp":
            return "hwp"
        if suffix == ".hwpx":
            return "hwpx"
        if suffix == ".docx":
            return "docx"

    module_name = source.__class__.__module__.split(".", 1)[0]
    if module_name == "hwpx":
        return "hwpx"
    if module_name == "docx":
        return "docx"

    raise ValueError(
        "Could not infer document type. Pass doc_type='hwp', 'hwpx', or 'docx'."
    )


def extract_styles(
    source: "HwpxDocument | DocxDocument | str | Path | bytes",
    *,
    doc_type: DocType = "auto",
    include_tables: bool = True,
) -> StyleMap:
    """Extract styles for HWP/HWPX/DOCX with one interface."""
    resolved = _resolve_doc_type(source, doc_type)

    if resolved == "hwp":
        if not isinstance(source, (str, Path)):
            raise TypeError("HWP conversion currently requires a filesystem path.")
        hwpx_bytes = convert_hwp_to_hwpx_bytes(source)
        return extract_styles_hwpx(hwpx_bytes)

    if resolved == "hwpx":
        return extract_styles_hwpx(source)

    return extract_styles_docx(source, include_tables=include_tables)


__all__ = [
    "DocType",
    "extract_styles",
    "extract_styles_docx",
    "extract_styles_hwpx",
]
