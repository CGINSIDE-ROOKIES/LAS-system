"""Format-agnostic style models for IR v2.

These models are embedded directly into IR nodes and can also be used as a
standalone lookup map when adapting legacy pipelines.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunStyleInfo(BaseModel):
    """Text-level formatting for a single run."""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    superscript: bool = False
    subscript: bool = False
    color: str | None = None
    highlight: str | None = None
    size_pt: float | None = None


class ParaStyleInfo(BaseModel):
    """Paragraph-level formatting."""

    align: str | None = None
    left_indent_pt: float | None = None
    right_indent_pt: float | None = None
    first_line_indent_pt: float | None = None
    hanging_indent_pt: float | None = None


class CellStyleInfo(BaseModel):
    """Table cell formatting."""

    background: str | None = None
    vertical_align: str | None = None
    horizontal_align: str | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    rowspan: int = 1
    colspan: int = 1


class TableStyleInfo(BaseModel):
    """Table-level metadata."""

    row_count: int = 0
    col_count: int = 0


class StyleMap(BaseModel):
    """Legacy-compatible style lookup map keyed by structural unit IDs."""

    runs: dict[str, RunStyleInfo] = Field(default_factory=dict)
    paragraphs: dict[str, ParaStyleInfo] = Field(default_factory=dict)
    cells: dict[str, CellStyleInfo] = Field(default_factory=dict)
    tables: dict[str, TableStyleInfo] = Field(default_factory=dict)


__all__ = [
    "RunStyleInfo",
    "ParaStyleInfo",
    "CellStyleInfo",
    "TableStyleInfo",
    "StyleMap",
]
