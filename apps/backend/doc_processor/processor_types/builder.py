"""Builder utilities for IR v2 from legacy structured mappings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from .ir_types import DocIR, ParagraphIR, RunIR, SourceType, TableCellIR, TableCellParagraphIR, TableIR
from .style_types import StyleMap

_LEGACY_NUM_RE = re.compile(r"\d+")
_PARAGRAPH_KEY_RE = re.compile(r"^(s\d+\.p\d+)")
_BODY_RUN_RE = re.compile(r"^(s\d+\.p\d+)\.r(\d+)$")
_TABLE_RUN_RE = re.compile(
    r"^(s\d+\.p\d+)\.r\d+\.tbl(\d+)\.tr(\d+)\.tc(\d+)\.p(\d+)(?:\.r(\d+))?$"
)
_TABLE_ROOT_RE = re.compile(r"^(s\d+\.p\d+\.r\d+\.tbl\d+)")


def normalize_text_default(text: str) -> str:
    """Default minimal normalization policy for v1 IR builders."""
    return text.strip()


def _legacy_id_sort_key(unit_id: str) -> tuple[tuple[int, ...], str]:
    nums = tuple(int(v) for v in _LEGACY_NUM_RE.findall(unit_id))
    return nums, unit_id


def _safe_para_for_id(
    paragraph_map: dict[str, ParagraphIR],
    paragraph_id: str,
    *,
    style_map: StyleMap | None,
) -> ParagraphIR:
    paragraph = paragraph_map.get(paragraph_id)
    if paragraph is not None:
        return paragraph

    para_style = style_map.paragraphs.get(paragraph_id) if style_map else None
    paragraph = ParagraphIR(unit_id=paragraph_id, para_style=para_style)
    paragraph_map[paragraph_id] = paragraph
    return paragraph


def _infer_source_doc_type(source_path: str | Path | None) -> str | None:
    if source_path is None:
        return None
    suffix = Path(source_path).suffix.lower()
    if suffix.startswith("."):
        suffix = suffix[1:]
    return suffix or None


def build_doc_ir_from_mapping(
    mapping: dict[str, str],
    *,
    style_map: StyleMap | None = None,
    source_path: str | Path | None = None,
    source_doc_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    normalizer: Callable[[str], str] | None = None,
    doc_id: str | None = None,
) -> DocIR:
    """Build :class:`DocIR` from legacy run-level mapping.

    Args:
        mapping: Legacy structured mapping keyed by unit IDs.
        style_map: Optional style lookup keyed by the same IDs.
        source_path: Optional source file path.
        source_doc_type: Optional document type; inferred from ``source_path`` when omitted.
        metadata: Optional free-form document metadata.
        normalizer: Optional text normalizer (default: ``str.strip``).
        doc_id: Optional stable document id; defaults to source stem when available.
    """
    normalize = normalizer or normalize_text_default

    paragraph_map: dict[str, ParagraphIR] = {}
    table_map: dict[str, TableIR] = {}
    cell_map: dict[tuple[str, int, int], TableCellIR] = {}
    cell_paragraph_map: dict[tuple[str, int, int, int], TableCellParagraphIR] = {}

    sorted_items = sorted(mapping.items(), key=lambda kv: _legacy_id_sort_key(kv[0]))

    for unit_id, text in sorted_items:
        paragraph_match = _PARAGRAPH_KEY_RE.match(unit_id)
        if not paragraph_match:
            continue

        paragraph_id = paragraph_match.group(1)
        paragraph = _safe_para_for_id(
            paragraph_map,
            paragraph_id,
            style_map=style_map,
        )

        table_run_match = _TABLE_RUN_RE.match(unit_id)
        if table_run_match:
            table_root_match = _TABLE_ROOT_RE.match(unit_id)
            if not table_root_match:
                continue

            table_root = table_root_match.group(1)
            _, _, tr_s, tc_s, cp_s, run_s = table_run_match.groups()
            tr = int(tr_s)
            tc = int(tc_s)
            cp = int(cp_s)
            run_idx = int(run_s or "1")
            run_id = unit_id if run_s is not None else f"{table_root}.tr{tr}.tc{tc}.p{cp}.r{run_idx}"

            paragraph.source_type = SourceType.TABLE_BLOCK

            table = table_map.get(table_root)
            if table is None:
                table_style = style_map.tables.get(table_root) if style_map else None
                table = TableIR(
                    unit_id=table_root,
                    row_count=table_style.row_count if table_style else 0,
                    col_count=table_style.col_count if table_style else 0,
                    table_style=table_style,
                )
                table_map[table_root] = table
                paragraph.tables.append(table)

            cell_bucket_key = (table_root, tr, tc)
            cell = cell_map.get(cell_bucket_key)
            if cell is None:
                cell_id = f"{table_root}.tr{tr}.tc{tc}"
                cell_style = style_map.cells.get(cell_id) if style_map else None
                cell = TableCellIR(
                    unit_id=cell_id,
                    row_index=tr,
                    col_index=tc,
                    cell_style=cell_style,
                )
                cell_map[cell_bucket_key] = cell
                table.cells.append(cell)

            cell_paragraph_bucket_key = (table_root, tr, tc, cp)
            cell_paragraph = cell_paragraph_map.get(cell_paragraph_bucket_key)
            if cell_paragraph is None:
                cell_paragraph_id = f"{table_root}.tr{tr}.tc{tc}.p{cp}"
                para_style = style_map.paragraphs.get(cell_paragraph_id) if style_map else None
                cell_paragraph = TableCellParagraphIR(
                    unit_id=cell_paragraph_id,
                    para_style=para_style,
                )
                cell_paragraph_map[cell_paragraph_bucket_key] = cell_paragraph
                cell.paragraphs.append(cell_paragraph)

            run_style = style_map.runs.get(run_id) if style_map else None
            run = RunIR(
                unit_id=run_id,
                text=text,
                normalized_text=normalize(text),
                run_style=run_style,
                inherited_source_type=SourceType.TABLE_CELL,
            )
            cell_paragraph.runs.append(run)
            continue

        body_run_match = _BODY_RUN_RE.match(unit_id)
        if body_run_match:
            run_style = style_map.runs.get(unit_id) if style_map else None
            paragraph.runs.append(
                RunIR(
                    unit_id=unit_id,
                    text=text,
                    normalized_text=normalize(text),
                    run_style=run_style,
                )
            )

    paragraphs = sorted(paragraph_map.values(), key=lambda p: _legacy_id_sort_key(p.unit_id))

    for paragraph in paragraphs:
        paragraph.runs.sort(key=lambda run: _legacy_id_sort_key(run.unit_id))
        paragraph.tables.sort(key=lambda table: _legacy_id_sort_key(table.unit_id))

        for table in paragraph.tables:
            table.cells.sort(key=lambda cell: (cell.row_index, cell.col_index))

            max_row = 0
            max_col = 0

            for cell in table.cells:
                max_row = max(max_row, cell.row_index)
                max_col = max(max_col, cell.col_index)

                cell.paragraphs.sort(key=lambda cp: _legacy_id_sort_key(cp.unit_id))
                for cell_paragraph in cell.paragraphs:
                    cell_paragraph.runs.sort(key=lambda run: _legacy_id_sort_key(run.unit_id))
                    cell_paragraph.text = "".join(run.text for run in cell_paragraph.runs)
                    cell_paragraph.normalized_text = normalize(cell_paragraph.text)

                cell.recompute_text(normalizer=normalize)

            if table.row_count <= 0:
                table.row_count = max_row
            if table.col_count <= 0:
                table.col_count = max_col

        paragraph.recompute_text(normalizer=normalize)
        paragraph.recompute_style_signal_summary()

    resolved_source_path = str(source_path) if source_path is not None else None
    resolved_doc_type = source_doc_type or _infer_source_doc_type(source_path)
    resolved_doc_id = doc_id
    if resolved_doc_id is None and source_path is not None:
        resolved_doc_id = Path(source_path).stem

    return DocIR(
        doc_id=resolved_doc_id,
        source_path=resolved_source_path,
        source_doc_type=resolved_doc_type,
        metadata=metadata or {},
        paragraphs=paragraphs,
    )


__all__ = ["build_doc_ir_from_mapping", "normalize_text_default"]
