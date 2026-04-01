"""Unified structured markdown exporter interface.

Use this module when you want one function name for both HWPX and DOCX:
``export_markdown_structured``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TYPE_CHECKING

from .docx_markdown_exporter import export_docx_markdown_structured
from .hwp_converter import convert_hwp_to_hwpx_bytes
from .hwpx_markdown_exporter import export_hwpx_markdown_structured

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


def export_markdown_structured(
    source: "HwpxDocument | DocxDocument | str | Path | bytes",
    *,
    doc_type: DocType = "auto",
    skip_empty: bool = False,
    include_tables: bool = True,
) -> dict[str, str]:
    """Export structured run-level mapping for HWPX or DOCX.

    Args:
        source: Document object, path, or (for HWPX) bytes.
        doc_type: Explicit format or ``"auto"`` for inference.
        skip_empty: If True, omit entries with empty text.
        include_tables: DOCX-only toggle for table extraction.

    Returns:
        ``dict[str, str]`` using the shared IR-friendly ID format.
    """
    resolved = _resolve_doc_type(source, doc_type)

    if resolved == "hwp":
        if not isinstance(source, (str, Path)):
            raise TypeError("HWP conversion currently requires a filesystem path.")
        hwpx_bytes = convert_hwp_to_hwpx_bytes(source)
        return export_hwpx_markdown_structured(hwpx_bytes, skip_empty=skip_empty)

    if resolved == "hwpx":
        return export_hwpx_markdown_structured(source, skip_empty=skip_empty)

    return export_docx_markdown_structured(
        source,
        include_tables=include_tables,
        skip_empty=skip_empty,
    )


__all__ = ["export_markdown_structured", "DocType"]
