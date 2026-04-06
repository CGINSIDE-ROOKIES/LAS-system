"""LAS wrappers over the standalone structural document processor builder."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from document_processor import build_doc_ir_from_mapping as _build_doc_ir_from_mapping
from document_processor import normalize_text_default

from .style_types import StyleMap


def build_doc_ir_from_mapping(
    mapping: dict[str, str],
    *,
    style_map: StyleMap | None = None,
    source_path: str | Path | None = None,
    source_doc_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    normalizer: Callable[[str], str] | None = None,
    doc_id: str | None = None,
):
    from .ir_types import DocIR

    base_doc = _build_doc_ir_from_mapping(
        mapping,
        style_map=style_map,
        source_path=source_path,
        source_doc_type=source_doc_type,
        metadata=metadata,
        normalizer=normalizer,
        doc_id=doc_id,
    )
    return DocIR.model_validate(base_doc.model_dump())


__all__ = ["build_doc_ir_from_mapping", "normalize_text_default"]
