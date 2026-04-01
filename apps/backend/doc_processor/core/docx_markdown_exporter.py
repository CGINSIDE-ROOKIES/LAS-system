"""DOCX structured markdown exporter.

Exports ``dict[str, str]`` in the same ID format used by HWPX exporters so
upstream IR construction can stay format-agnostic.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument


def _iter_blocks(
    doc,
    *,
    CT_P,
    CT_Tbl,
    Paragraph,
    Table,
) -> Iterator[object]:
    """Yield document blocks (paragraphs/tables) in source order.

    Uses ``iter_inner_content`` when available. Falls back to XML traversal for
    compatibility with python-docx versions that do not expose it.
    """
    iter_inner_content = getattr(doc, "iter_inner_content", None)
    if callable(iter_inner_content):
        yield from iter_inner_content()
        return

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def export_docx_markdown_structured(
    source: "DocxDocument | str | Path",
    *,
    include_tables: bool = True,
    skip_empty: bool = False,
) -> dict[str, str]:
    """Export DOCX text fragments keyed by HWPX-compatible IDs.

    ID format (1-based indices):
    - Body runs: ``s1.p{paragraph}.r{run}``
    - Table cell runs:
      ``s1.p{paragraph}.r1.tbl{table}.tr{row}.tc{col}.p{cell_para}.r{cell_run}``

    Args:
        source: Open python-docx ``Document`` or path to ``.docx``.
        include_tables: Include table content in the output mapping.
        skip_empty: If True, omit entries with empty text.
    """
    from docx import Document as load_docx
    from docx.document import Document as DocxDocument
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = source if isinstance(source, DocxDocument) else load_docx(str(source))
    mapping: dict[str, str] = {}

    p_idx = 0
    tbl_counter = 0

    for block in _iter_blocks(
        doc,
        CT_P=CT_P,
        CT_Tbl=CT_Tbl,
        Paragraph=Paragraph,
        Table=Table,
    ):
        if isinstance(block, Paragraph):
            p_idx += 1
            base = f"s1.p{p_idx}"

            if not block.runs:
                text = block.text
                if skip_empty and not text:
                    continue
                mapping[f"{base}.r1"] = text
                continue

            for r_idx, run in enumerate(block.runs, start=1):
                text = run.text
                if skip_empty and not text:
                    continue
                mapping[f"{base}.r{r_idx}"] = text
            continue

        if not include_tables or not isinstance(block, Table):
            continue

        tbl_counter += 1
        p_idx += 1
        tbl_base = f"s1.p{p_idx}.r1.tbl{tbl_counter}"

        for tr_idx, row in enumerate(block.rows, start=1):
            for tc_idx, cell in enumerate(row.cells, start=1):
                for cp_idx, cell_para in enumerate(cell.paragraphs, start=1):
                    if not cell_para.runs:
                        text = cell_para.text
                        if skip_empty and not text:
                            continue
                        key = f"{tbl_base}.tr{tr_idx}.tc{tc_idx}.p{cp_idx}.r1"
                        mapping[key] = text
                        continue

                    for cr_idx, run in enumerate(cell_para.runs, start=1):
                        text = run.text
                        if skip_empty and not text:
                            continue
                        key = f"{tbl_base}.tr{tr_idx}.tc{tc_idx}.p{cp_idx}.r{cr_idx}"
                        mapping[key] = text

    return mapping


def export_markdown_structured(
    source: "DocxDocument | str | Path",
    *,
    include_tables: bool = True,
    skip_empty: bool = False,
) -> dict[str, str]:
    """Compatibility alias for a consistent exporter function name."""
    return export_docx_markdown_structured(
        source,
        include_tables=include_tables,
        skip_empty=skip_empty,
    )


__all__ = ["export_docx_markdown_structured", "export_markdown_structured"]
