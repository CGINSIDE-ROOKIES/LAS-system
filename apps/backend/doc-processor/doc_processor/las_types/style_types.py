"""
Style types — format-agnostic style representations
=====================================================

These types live *alongside* the IR, not inside it.  The IR remains
LLM-focused (plain text + structural IDs).  Style information is
extracted separately and keyed by the same chunk IDs so it can be
recombined at render time (e.g. HTML export).

Hierarchy::

    StyleMap
    ├── runs: dict[chunk_id, RunStyleInfo]    — per-run text formatting
    ├── paragraphs: dict[para_key, ParaStyleInfo] — per-paragraph alignment
    ├── cells: dict[cell_key, CellStyleInfo]  — per-cell table styling
    └── tables: dict[tbl_root, TableStyleInfo] — per-table metadata
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunStyleInfo(BaseModel):
    """Text-level formatting for a single run (applies to both body and table cell runs)."""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    superscript: bool = False
    subscript: bool = False
    color: str | None = None          # hex "#RRGGBB" or None (inherit)
    highlight: str | None = None      # background highlight hex or None
    size_pt: float | None = None      # font size in points, None = inherit


class ParaStyleInfo(BaseModel):
    """Paragraph-level formatting.

    Keyed by paragraph key, e.g. ``"s1.p5"``  (body) or
    ``"s1.p5.r1.tbl1.tr2.tc3.p1"`` (table cell paragraph).
    """
    align: str | None = None  # "left" | "center" | "right" | "justify"


class CellStyleInfo(BaseModel):
    """Table cell formatting.

    Keyed by cell address string, e.g. ``"s1.p5.r1.tbl1.tr2.tc3"``.
    """
    background: str | None = None     # fill color hex "#RRGGBB"
    vertical_align: str | None = None # "top" | "center" | "bottom"
    horizontal_align: str | None = None  # "left" | "center" | "right" | "justify"
    border_top: str | None = None     # CSS shorthand e.g. "1px solid #000000"
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    rowspan: int = 1
    colspan: int = 1


class TableStyleInfo(BaseModel):
    """Table-level metadata.

    Keyed by table root ID, e.g. ``"s1.p5.r1.tbl1"``.
    """
    row_count: int = 0
    col_count: int = 0


class StyleMap(BaseModel):
    """Complete style information for a document, parallel to the IR."""
    runs: dict[str, RunStyleInfo] = Field(default_factory=dict)
    paragraphs: dict[str, ParaStyleInfo] = Field(default_factory=dict)
    cells: dict[str, CellStyleInfo] = Field(default_factory=dict)
    tables: dict[str, TableStyleInfo] = Field(default_factory=dict)
