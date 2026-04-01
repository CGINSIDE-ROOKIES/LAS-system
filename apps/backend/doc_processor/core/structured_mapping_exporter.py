"""Unified structured mapping exporter interface.

Exports run-level structural mappings (unit-id -> text) across HWP/HWPX/DOCX.
This does not emit Markdown text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TYPE_CHECKING

from .docx_structured_exporter import export_docx_structured_mapping
from .hwp_converter import convert_hwp_to_hwpx_bytes
from .hwpx_structured_exporter import export_hwpx_structured_mapping

if TYPE_CHECKING:
    from docx.document import Document as DocxDocument
    from hwpx import HwpxDocument


DocType = Literal["auto", "hwp", "hwpx", "docx"]


def _resolve_doc_type(source: object, doc_type: DocType) -> Literal["hwp", "hwpx", "docx"]:
    if doc_type in ("hwp", "hwpx", "docx"):
        return doc_type

    if isinstance(source, bytes):
        # Bytes are supported only for HWPX.
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


def export_structured_mapping(
    source: "HwpxDocument | DocxDocument | str | Path | bytes",
    *,
    doc_type: DocType = "auto",
    skip_empty: bool = False,
    include_tables: bool = True,
) -> dict[str, str]:
    """Export structured run-level mapping for HWPX/DOCX/HWP."""
    resolved = _resolve_doc_type(source, doc_type)

    if resolved == "hwp":
        if not isinstance(source, (str, Path)):
            raise TypeError("HWP conversion currently requires a filesystem path.")
        hwpx_bytes = convert_hwp_to_hwpx_bytes(source)
        return export_hwpx_structured_mapping(hwpx_bytes, skip_empty=skip_empty)

    if resolved == "hwpx":
        return export_hwpx_structured_mapping(source, skip_empty=skip_empty)

    return export_docx_structured_mapping(
        source,
        include_tables=include_tables,
        skip_empty=skip_empty,
    )


__all__ = ["DocType", "export_structured_mapping"]
