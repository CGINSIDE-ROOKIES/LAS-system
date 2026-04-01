"""HWPX structured markdown exporter.

This module reproduces ``export_markdown_structured`` output shape without
patching upstream ``python-hwpx``.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET
import zipfile

if TYPE_CHECKING:
    from hwpx import HwpxDocument

_HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = f"{{{_HP_NS}}}"


def _emit_run(mapping: dict[str, str], key: str, text: str | None, skip_empty: bool) -> None:
    value = text or ""
    if skip_empty and not value:
        return
    mapping[key] = value


def _run_text(run_el: ET.Element) -> str:
    # Only consume direct hp:t children to preserve run boundaries.
    return "".join((t.text or "") for t in run_el.findall(f"{_HP}t"))


def _paragraph_text(paragraph_el: ET.Element) -> str:
    return "".join(_run_text(run_el) for run_el in paragraph_el.findall(f"{_HP}run"))


def _iter_section_paragraphs(section_root: ET.Element) -> list[ET.Element]:
    return section_root.findall(f"{_HP}p")


def _iter_paragraph_tables(paragraph_el: ET.Element) -> list[ET.Element]:
    # Tables are anchored in paragraph runs.
    return paragraph_el.findall(f"{_HP}run/{_HP}tbl")


def _iter_cell_paragraphs(cell_el: ET.Element) -> list[ET.Element]:
    direct = cell_el.findall(f"{_HP}subList/{_HP}p")
    if direct:
        return direct
    return cell_el.findall(f".//{_HP}p")


def _export_table_xml(
    mapping: dict[str, str],
    table_el: ET.Element,
    tbl_root: str,
    *,
    skip_empty: bool,
) -> None:
    for tr_idx, row_el in enumerate(table_el.findall(f"{_HP}tr"), start=1):
        for tc_idx, cell_el in enumerate(row_el.findall(f"{_HP}tc"), start=1):
            cell_paragraphs = _iter_cell_paragraphs(cell_el)
            if not cell_paragraphs:
                key = f"{tbl_root}.tr{tr_idx}.tc{tc_idx}.p1.r1"
                _emit_run(mapping, key, "", skip_empty)
                continue

            for cp_idx, cp_el in enumerate(cell_paragraphs, start=1):
                runs = cp_el.findall(f"{_HP}run")
                if not runs:
                    key = f"{tbl_root}.tr{tr_idx}.tc{tc_idx}.p{cp_idx}.r1"
                    _emit_run(mapping, key, _paragraph_text(cp_el), skip_empty)
                    continue

                for cr_idx, run_el in enumerate(runs, start=1):
                    key = f"{tbl_root}.tr{tr_idx}.tc{tc_idx}.p{cp_idx}.r{cr_idx}"
                    _emit_run(mapping, key, _run_text(run_el), skip_empty)


def _export_from_section_roots(section_roots: list[ET.Element], *, skip_empty: bool) -> dict[str, str]:
    mapping: dict[str, str] = {}

    for s_idx, section_root in enumerate(section_roots, start=1):
        for p_idx, para_el in enumerate(_iter_section_paragraphs(section_root), start=1):
            base = f"s{s_idx}.p{p_idx}"
            run_els = para_el.findall(f"{_HP}run")

            if not run_els:
                _emit_run(mapping, f"{base}.r1", _paragraph_text(para_el), skip_empty)
            else:
                for r_idx, run_el in enumerate(run_els, start=1):
                    _emit_run(mapping, f"{base}.r{r_idx}", _run_text(run_el), skip_empty)

            for t_idx, table_el in enumerate(_iter_paragraph_tables(para_el), start=1):
                # Keep tbl numbering scoped to each paragraph.
                tbl_root = f"{base}.r1.tbl{t_idx}"
                _export_table_xml(mapping, table_el, tbl_root, skip_empty=skip_empty)

    return mapping


def _section_roots_from_bytes(source: bytes) -> list[ET.Element]:
    names: list[str] = []
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


def _section_roots_from_doc(doc: "HwpxDocument") -> list[ET.Element]:
    return [section.element for section in doc.sections]


def export_hwpx_markdown_structured(
    source: "HwpxDocument | str | Path | bytes",
    *,
    skip_empty: bool = False,
) -> dict[str, str]:
    """Export HWPX text fragments keyed by structural run IDs.

    Args:
        source: ``HwpxDocument``, ``.hwpx`` path, or raw HWPX bytes.
        skip_empty: If True, omit entries with empty text.
    """
    from hwpx import HwpxDocument

    if isinstance(source, HwpxDocument):
        return _export_from_section_roots(
            _section_roots_from_doc(source),
            skip_empty=skip_empty,
        )

    if isinstance(source, bytes):
        return _export_from_section_roots(
            _section_roots_from_bytes(source),
            skip_empty=skip_empty,
        )

    if isinstance(source, (str, Path)):
        with HwpxDocument.open(str(source)) as doc:
            return _export_from_section_roots(
                _section_roots_from_doc(doc),
                skip_empty=skip_empty,
            )

    raise TypeError(
        "source must be HwpxDocument, bytes, or a .hwpx path, "
        f"got {type(source)!r}"
    )


def export_markdown_structured(
    source: "HwpxDocument | str | Path | bytes",
    *,
    skip_empty: bool = False,
) -> dict[str, str]:
    """Compatibility alias for a consistent exporter function name."""
    return export_hwpx_markdown_structured(source, skip_empty=skip_empty)


__all__ = ["export_hwpx_markdown_structured", "export_markdown_structured"]
