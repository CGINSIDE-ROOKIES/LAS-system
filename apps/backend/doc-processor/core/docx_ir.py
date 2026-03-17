"""
docx_ir — DOCX document to structured IR mapping
==================================================

Mirrors the output format of ``hwpx.tools.exporter.export_markdown_structured``
so that the same ``create_ir_dict_from_mapping`` pipeline can process both
HWPX and DOCX files.

ID format (1-based indices, matching HWPX convention):
    - Normal runs:  ``s1.p{paragraph}.r{run}``
    - Table cells:  ``s1.p{paragraph}.r1.tbl{table}.tr{row}.tc{col}.p{cell_para}.r{cell_run}``

Section index is always ``s1`` — DOCX sections are page-layout constructs,
not content groupings (same behaviour as the HWPX pipeline where sections
are effectively stuck at s1).
"""

from __future__ import annotations

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from pathlib import Path


def export_docx_structured(
    source: str | Path,
    *,
    include_tables: bool = True,
    skip_empty: bool = True,
) -> dict[str, str]:
    """Export DOCX text fragments keyed by structural IDs.

    Returns the same ``dict[str, str]`` shape as the HWPX
    ``export_markdown_structured`` function.
    """
    doc = DocxDocument(str(source))
    mapping: dict[str, str] = {}

    p_idx = 0          # global paragraph counter (1-based after increment)
    tbl_counter = 0    # global table counter

    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            p_idx += 1
            base = f"s1.p{p_idx}"

            runs = block.runs
            if not runs:
                text = block.text
                if skip_empty and not text:
                    continue
                # No runs — emit as a single virtual run
                mapping[f"{base}.r1"] = text
                continue

            for r_idx, run in enumerate(runs, start=1):
                text = run.text
                if skip_empty and not text:
                    continue
                mapping[f"{base}.r{r_idx}"] = text

        elif isinstance(block, Table) and include_tables:
            tbl_counter += 1
            # Assign a host paragraph for the table (matches HWPX convention
            # where tables live inside a paragraph/run).
            p_idx += 1
            tbl_base = f"s1.p{p_idx}.r1.tbl{tbl_counter}"

            for tr_idx, row in enumerate(block.rows, start=1):
                for tc_idx, cell in enumerate(row.cells, start=1):
                    for cp_idx, cell_para in enumerate(cell.paragraphs, start=1):
                        cell_runs = cell_para.runs
                        if not cell_runs:
                            text = cell_para.text
                            if skip_empty and not text:
                                continue
                            key = f"{tbl_base}.tr{tr_idx}.tc{tc_idx}.p{cp_idx}.r1"
                            mapping[key] = text
                            continue

                        for cr_idx, cr in enumerate(cell_runs, start=1):
                            text = cr.text
                            if skip_empty and not text:
                                continue
                            key = f"{tbl_base}.tr{tr_idx}.tc{tc_idx}.p{cp_idx}.r{cr_idx}"
                            mapping[key] = text

    return mapping
