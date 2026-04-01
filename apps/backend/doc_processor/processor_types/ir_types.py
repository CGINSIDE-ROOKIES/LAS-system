"""IR v2 models.

Hierarchy:
    DocIR -> ParagraphIR -> RunIR
                    \\-> TableIR -> TableCellIR -> TableCellParagraphIR -> RunIR
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from .style_types import CellStyleInfo, ParaStyleInfo, RunStyleInfo, TableStyleInfo

if TYPE_CHECKING:
    from .style_types import StyleMap


BBox = tuple[float, float, float, float]


class SourceType(str, Enum):
    """Core paragraph source categories for IR v2."""

    PARAGRAPH = "paragraph"
    LINE = "line"
    TABLE_CELL = "table_cell"
    HEADER_FOOTER_CANDIDATE = "header_footer_candidate"
    TABLE_BLOCK = "table_block"


class ParserSignals(BaseModel):
    """Typed parser/CRF signals with support for additional custom keys."""

    model_config = ConfigDict(extra="allow")

    regex_article: bool | None = None
    regex_subclause: bool | None = None
    indent_level: int | None = None
    centered: bool | None = None
    font_size: float | None = None
    bold: bool | None = None


class RunIR(BaseModel):
    """Smallest style-preserving text unit."""

    unit_id: str
    text: str = ""
    normalized_text: str = ""
    run_style: RunStyleInfo | None = None

    # Inherited paragraph-level semantic metadata
    candidate_labels: list[str] = Field(default_factory=list)
    parser_confidence: float | None = None
    final_label: str | None = None
    inherited_source_type: SourceType | None = None


class TableCellParagraphIR(BaseModel):
    """Paragraph inside a table cell."""

    unit_id: str
    text: str = ""
    normalized_text: str = ""
    para_style: ParaStyleInfo | None = None
    runs: list[RunIR] = Field(default_factory=list)


class TableCellIR(BaseModel):
    """Table cell node."""

    unit_id: str
    row_index: int
    col_index: int
    text: str = ""
    normalized_text: str = ""
    cell_style: CellStyleInfo | None = None
    paragraphs: list[TableCellParagraphIR] = Field(default_factory=list)

    def recompute_text(self, *, normalizer: Callable[[str], str] | None = None) -> None:
        normalize = normalizer or (lambda s: s.strip())
        self.text = "\n".join(p.text for p in self.paragraphs)
        self.normalized_text = normalize(self.text)


class TableIR(BaseModel):
    """Nested table node under a paragraph."""

    unit_id: str
    row_count: int = 0
    col_count: int = 0
    table_style: TableStyleInfo | None = None
    cells: list[TableCellIR] = Field(default_factory=list)


class ParagraphIR(BaseModel):
    """Semantic/structural paragraph unit fed to categorization."""

    unit_id: str
    page: int | None = None
    bbox: BBox | None = None

    text: str = ""
    normalized_text: str = ""

    source_type: SourceType = SourceType.PARAGRAPH
    parser_signals: ParserSignals = Field(default_factory=ParserSignals)
    candidate_labels: list[str] = Field(default_factory=list)
    parser_confidence: float | None = None
    final_label: str | None = None

    para_style: ParaStyleInfo | None = None
    runs: list[RunIR] = Field(default_factory=list)
    tables: list[TableIR] = Field(default_factory=list)

    def iter_all_runs(self, *, include_table_runs: bool = True):
        """Yield all child runs, optionally including runs inside nested tables."""
        yield from self.runs
        if not include_table_runs:
            return
        for table in self.tables:
            for cell in table.cells:
                for cp in cell.paragraphs:
                    yield from cp.runs

    def recompute_style_signal_summary(self) -> None:
        """Recompute paragraph-level style-derived parser signals from child runs."""
        styles = [run.run_style for run in self.iter_all_runs() if run.run_style is not None]
        if not styles:
            return

        sizes = [style.size_pt for style in styles if style.size_pt is not None]
        if sizes:
            self.parser_signals.font_size = float(sum(sizes) / len(sizes))

        self.parser_signals.bold = any(style.bold for style in styles)

        if self.para_style and self.para_style.align is not None:
            self.parser_signals.centered = self.para_style.align == "center"

    def recompute_text(self, *, normalizer: Callable[[str], str] | None = None) -> None:
        """Recompute paragraph text/normalized_text from child content."""
        normalize = normalizer or (lambda s: s.strip())

        if self.source_type == SourceType.TABLE_BLOCK and self.tables:
            parts: list[str] = []
            if self.runs:
                parts.append("".join(run.text for run in self.runs))
            for table in self.tables:
                cell_texts = [cell.text for cell in table.cells if cell.text]
                if cell_texts:
                    parts.append("\n".join(cell_texts))
            self.text = "\n".join(part for part in parts if part)
        else:
            self.text = "".join(run.text for run in self.runs)

        self.normalized_text = normalize(self.text)

    def propagate_semantics_to_runs(self, *, include_table_runs: bool = True) -> None:
        """Propagate paragraph semantic fields to child runs for downstream consumers."""
        for run in self.iter_all_runs(include_table_runs=include_table_runs):
            run.candidate_labels = list(self.candidate_labels)
            run.parser_confidence = self.parser_confidence
            run.final_label = self.final_label
            run.inherited_source_type = self.source_type


class DocIR(BaseModel):
    """Top-level container for parsed IR v2."""

    doc_id: str | None = None
    source_path: str | None = None
    source_doc_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    paragraphs: list[ParagraphIR] = Field(default_factory=list)

    @classmethod
    def from_mapping(
        cls,
        mapping: dict[str, str],
        *,
        style_map: StyleMap | None = None,
        source_path: str | Path | None = None,
        source_doc_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        normalizer: Callable[[str], str] | None = None,
        doc_id: str | None = None,
    ) -> DocIR:
        """Build :class:`DocIR` from legacy structured mapping output."""
        from .builder import build_doc_ir_from_mapping

        return build_doc_ir_from_mapping(
            mapping,
            style_map=style_map,
            source_path=source_path,
            source_doc_type=source_doc_type,
            metadata=metadata,
            normalizer=normalizer,
            doc_id=doc_id,
        )

    def propagate_semantics_to_runs(self) -> None:
        """Propagate semantic fields from paragraphs into all child runs."""
        for paragraph in self.paragraphs:
            paragraph.propagate_semantics_to_runs()


__all__ = [
    "BBox",
    "DocIR",
    "ParagraphIR",
    "RunIR",
    "SourceType",
    "ParserSignals",
    "TableIR",
    "TableCellIR",
    "TableCellParagraphIR",
]
