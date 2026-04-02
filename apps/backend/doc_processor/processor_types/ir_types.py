"""IR v2 models.

Hierarchy:
    DocIR -> ParagraphIR -> RunIR
                    \\-> TableIR -> TableCellIR -> TableCellParagraphIR -> RunIR
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Callable, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from .style_types import CellStyleInfo, ParaStyleInfo, RunStyleInfo, TableStyleInfo

if TYPE_CHECKING:
    from .style_types import StyleMap


BBox = tuple[float, float, float, float]

DocStructureLabel: TypeAlias = Literal[
    "title",
    "header",
    "footer",
    "preamble",
    "clause",
    "subclause",
    "body",
    "signature_block",
    "input_box",
    "table_block",
    "table_cell",
    "appendix",
    "other",
]

ReviewStatus: TypeAlias = Literal["ok", "fix", "split"]


_CLAUSE_PATTERN = r"제\s*(\d+)\s*조"
_CLAUSE_FALLBACK_PATTERN = r"^\s*(\d+)\.\s"
_SUBCLAUSE_PATTERN = (
    r"\((\d+)\)|"
    r"([\u2460-\u2473\u2474-\u2487\u2488-\u249B\u24EA\u24F5-\u24FE\u2776-\u277F\u2780-\u2789\u278A-\u2793])"
)
_LEGACY_NUM_RE = re.compile(r"\d+")


def _legacy_id_sort_key(unit_id: str) -> tuple[tuple[int, ...], str]:
    nums = tuple(int(v) for v in _LEGACY_NUM_RE.findall(unit_id))
    return nums, unit_id


def _enclosed_number_value(ch: str) -> int | None:
    cp = ord(ch)
    if 0x2460 <= cp <= 0x2473:
        return cp - 0x2460 + 1
    if 0x2474 <= cp <= 0x2487:
        return cp - 0x2474 + 1
    if 0x2488 <= cp <= 0x249B:
        return cp - 0x2488 + 1
    if cp == 0x24EA:
        return 0
    if 0x24F5 <= cp <= 0x24FE:
        return cp - 0x24F5 + 1
    if 0x2776 <= cp <= 0x277F:
        return cp - 0x2776 + 1
    if 0x2780 <= cp <= 0x2789:
        return cp - 0x2780 + 1
    if 0x278A <= cp <= 0x2793:
        return cp - 0x278A + 1
    return None


def _find_occurrence(text: str, needle: str, occurrence: int) -> int | None:
    if not needle:
        return None

    if occurrence <= 0:
        occurrence = 1

    start = 0
    seen = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            return None
        seen += 1
        if seen == occurrence:
            return idx
        start = idx + 1


class SourceType(str, Enum):
    """Core paragraph source categories for IR v2."""

    PARAGRAPH = "paragraph"
    LINE = "line"
    TABLE_CELL = "table_cell"
    HEADER_FOOTER_CANDIDATE = "header_footer_candidate"
    TABLE_BLOCK = "table_block"


class RegexNumberMatch(BaseModel):
    """Regex-detected numbering match."""

    value: str
    span: tuple[int, int]
    pattern: str
    matched_text: str


class ParserSignals(BaseModel):
    """Typed parser/CRF signals with support for additional custom keys."""

    model_config = ConfigDict(extra="allow")

    regex_clause: RegexNumberMatch | None = None
    regex_subclause: RegexNumberMatch | None = None
    provisional_clause_no: str | None = None
    provisional_subclause_no: str | None = None
    indent_level: int | None = None
    centered: bool | None = None
    font_size: float | None = None
    bold: float | None = None


class SegmentRunSpan(BaseModel):
    """Overlap of a semantic segment with one run."""

    run_unit_id: str
    run_local_start: int
    run_local_end: int


class ParagraphSegmentIR(BaseModel):
    """Semantic segment inside one paragraph."""

    segment_id: str
    start: int
    end: int
    text: str = ""
    normalized_text: str = ""
    status: ReviewStatus = "split"
    reason: str | None = None
    label: DocStructureLabel | None = None
    candidate_labels: list[DocStructureLabel] = Field(default_factory=list)
    run_spans: list[SegmentRunSpan] = Field(default_factory=list)
    font_size: float | None = None
    bold: float | None = None


class SplitOp(BaseModel):
    """LLM split op contract (incoming)."""

    op: Literal["split_unit"] = "split_unit"
    anchor_text: str
    occurrence: int = 1
    left_label: DocStructureLabel | None = None
    right_label: DocStructureLabel | None = None
    left_candidate_labels: list[DocStructureLabel] = Field(default_factory=list)
    right_candidate_labels: list[DocStructureLabel] = Field(default_factory=list)


class ParagraphReviewResult(BaseModel):
    """LLM per-paragraph review result contract."""

    unit_id: str
    status: ReviewStatus
    label: DocStructureLabel | None = None
    candidate_labels: list[DocStructureLabel] = Field(default_factory=list)
    reason: str | None = None
    ops: list[SplitOp] = Field(default_factory=list)


class RunIR(BaseModel):
    """Smallest style-preserving text unit."""

    unit_id: str
    text: str = ""
    normalized_text: str = ""
    run_style: RunStyleInfo | None = None

    # Inherited paragraph-level semantic metadata
    candidate_labels: list[DocStructureLabel] = Field(default_factory=list)
    parser_confidence: float | None = None
    final_label: DocStructureLabel | None = None
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
    candidate_labels: list[DocStructureLabel] = Field(default_factory=list)
    parser_confidence: float | None = None
    final_label: DocStructureLabel | None = None

    para_style: ParaStyleInfo | None = None
    runs: list[RunIR] = Field(default_factory=list)
    tables: list[TableIR] = Field(default_factory=list)
    segments: list[ParagraphSegmentIR] = Field(default_factory=list)

    def iter_all_runs(self, *, include_table_runs: bool = True):
        """Yield all child runs, optionally including runs inside nested tables."""
        yield from self.runs
        if not include_table_runs:
            return
        for table in self.tables:
            for cell in table.cells:
                for cp in cell.paragraphs:
                    yield from cp.runs

    def _style_summary_from_runs(self, runs: list[RunIR]) -> tuple[float | None, float | None]:
        sizes = [
            run.run_style.size_pt
            for run in runs
            if run.run_style is not None and run.run_style.size_pt is not None
        ]
        avg_font_size = float(sum(sizes) / len(sizes)) if sizes else None

        bold_chars = 0
        total_chars = 0
        for run in runs:
            run_chars = sum(1 for ch in run.text if not ch.isspace())
            total_chars += run_chars
            if run_chars > 0 and run.run_style is not None and run.run_style.bold:
                bold_chars += run_chars

        bold_ratio = (bold_chars / total_chars) if total_chars > 0 else None
        return avg_font_size, bold_ratio

    def _run_char_spans(self) -> list[tuple[RunIR, int, int]]:
        spans: list[tuple[RunIR, int, int]] = []
        cursor = 0
        for run in self.runs:
            end = cursor + len(run.text)
            spans.append((run, cursor, end))
            cursor = end
        return spans

    def _populate_segment_run_spans(self) -> None:
        run_spans = self._run_char_spans()
        for segment in self.segments:
            overlaps: list[SegmentRunSpan] = []
            for run, run_start, run_end in run_spans:
                overlap_start = max(segment.start, run_start)
                overlap_end = min(segment.end, run_end)
                if overlap_start >= overlap_end:
                    continue
                overlaps.append(
                    SegmentRunSpan(
                        run_unit_id=run.unit_id,
                        run_local_start=overlap_start - run_start,
                        run_local_end=overlap_end - run_start,
                    )
                )
            segment.run_spans = overlaps

    def recompute_segment_style_signals(self) -> None:
        if not self.segments:
            return

        run_by_id = {run.unit_id: run for run in self.runs}
        for segment in self.segments:
            segment_runs: list[RunIR] = []
            for span in segment.run_spans:
                run = run_by_id.get(span.run_unit_id)
                if run is not None:
                    segment_runs.append(run)
            font_size, bold_ratio = self._style_summary_from_runs(segment_runs)
            segment.font_size = font_size
            segment.bold = bold_ratio

    def recompute_style_signal_summary(self, *, include_table_runs: bool = True) -> None:
        """Recompute paragraph-level style-derived parser signals from child runs."""
        runs = list(self.iter_all_runs(include_table_runs=include_table_runs))
        font_size, bold_ratio = self._style_summary_from_runs(runs)

        self.parser_signals.font_size = font_size
        self.parser_signals.bold = bold_ratio

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

    def apply_review_result(self, result: ParagraphReviewResult, *, strict: bool = False) -> None:
        if result.candidate_labels:
            self.candidate_labels = list(result.candidate_labels)
        if result.label is not None:
            self.final_label = result.label

        if result.status != "split":
            self.segments = []
            return

        text = self.text
        if not text:
            self.segments = []
            return

        boundaries = {0, len(text)}
        ops_by_boundary: dict[int, list[SplitOp]] = {}
        for op in result.ops:
            if op.op != "split_unit":
                continue
            idx = _find_occurrence(text, op.anchor_text, op.occurrence)
            if idx is None:
                if strict:
                    raise ValueError(
                        f"Could not resolve split anchor '{op.anchor_text}' "
                        f"(occurrence {op.occurrence}) for {self.unit_id}"
                    )
                continue
            if idx <= 0 or idx >= len(text):
                continue
            boundaries.add(idx)
            ops_by_boundary.setdefault(idx, []).append(op)

        sorted_bounds = sorted(boundaries)
        segments: list[ParagraphSegmentIR] = []
        for idx in range(len(sorted_bounds) - 1):
            start = sorted_bounds[idx]
            end = sorted_bounds[idx + 1]
            seg_text = text[start:end]

            seg_label = result.label
            seg_candidates = list(result.candidate_labels)

            left_ops = ops_by_boundary.get(end, [])
            for op in left_ops:
                if op.left_label is not None:
                    seg_label = op.left_label
                if op.left_candidate_labels:
                    seg_candidates = list(op.left_candidate_labels)

            right_ops = ops_by_boundary.get(start, [])
            for op in right_ops:
                if op.right_label is not None:
                    seg_label = op.right_label
                if op.right_candidate_labels:
                    seg_candidates = list(op.right_candidate_labels)

            segments.append(
                ParagraphSegmentIR(
                    segment_id=f"{self.unit_id}.seg{idx + 1}",
                    start=start,
                    end=end,
                    text=seg_text,
                    normalized_text=seg_text.strip(),
                    status=result.status,
                    reason=result.reason,
                    label=seg_label,
                    candidate_labels=seg_candidates,
                )
            )

        self.segments = segments
        self._populate_segment_run_spans()
        self.recompute_segment_style_signals()


class DocIR(BaseModel):
    """Top-level container for parsed IR v2."""

    doc_id: str | None = None
    source_path: str | None = None
    source_doc_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    paragraphs: list[ParagraphIR] = Field(default_factory=list)

    @classmethod
    def from_file(
        cls,
        source: str | Path,
        *,
        doc_type: Literal["auto", "hwp", "hwpx", "docx"] = "auto",
        include_tables: bool = True,
        skip_empty: bool = False,
        include_table_cells_for_numbering: bool = False,
        metadata: dict[str, Any] | None = None,
        normalizer: Callable[[str], str] | None = None,
        doc_id: str | None = None,
    ) -> DocIR:
        """Build and preprocess :class:`DocIR` from a file path in one call."""
        source_path = Path(source)

        if doc_type == "auto":
            suffix = source_path.suffix.lower()
            if suffix == ".hwp":
                resolved_doc_type: Literal["hwp", "hwpx", "docx"] = "hwp"
            elif suffix == ".hwpx":
                resolved_doc_type = "hwpx"
            elif suffix == ".docx":
                resolved_doc_type = "docx"
            else:
                raise ValueError(
                    "Could not infer document type from file extension. "
                    "Pass doc_type='hwp', 'hwpx', or 'docx'."
                )
        else:
            resolved_doc_type = doc_type

        from core.structured_mapping_exporter import export_structured_mapping
        from core.style_extractor import extract_styles

        if resolved_doc_type == "hwp":
            from core.hwp_converter import convert_hwp_to_hwpx_bytes

            hwpx_bytes = convert_hwp_to_hwpx_bytes(source_path)
            mapping = export_structured_mapping(
                hwpx_bytes,
                doc_type="hwpx",
                skip_empty=skip_empty,
                include_tables=include_tables,
            )
            style_map = extract_styles(
                hwpx_bytes,
                doc_type="hwpx",
                include_tables=include_tables,
            )
        else:
            mapping = export_structured_mapping(
                source_path,
                doc_type=resolved_doc_type,
                skip_empty=skip_empty,
                include_tables=include_tables,
            )
            style_map = extract_styles(
                source_path,
                doc_type=resolved_doc_type,
                include_tables=include_tables,
            )

        doc_ir = cls.from_mapping(
            mapping,
            style_map=style_map,
            source_path=source_path,
            source_doc_type=resolved_doc_type,
            metadata=metadata,
            normalizer=normalizer,
            doc_id=doc_id,
        )
        doc_ir.annotate_numbering_signals(
            include_table_cells=include_table_cells_for_numbering
        )
        doc_ir.recompute_style_signals(include_table_runs=True)
        return doc_ir

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

    def _iter_scan_paragraphs(
        self,
        *,
        include_table_cells: bool,
    ) -> list[tuple[ParagraphIR, str]]:
        scan_items: list[tuple[ParagraphIR, str]] = []
        for paragraph in sorted(self.paragraphs, key=lambda p: _legacy_id_sort_key(p.unit_id)):
            if paragraph.source_type == SourceType.TABLE_BLOCK and not include_table_cells:
                text = "".join(run.text for run in paragraph.runs)
            else:
                text = paragraph.text
            scan_items.append((paragraph, text))
        return scan_items

    def _get_clause_matches(
        self,
        text: str,
        *,
        allow_fallback: bool,
    ) -> list[RegexNumberMatch]:
        results: list[RegexNumberMatch] = []
        postposition_chars = set("에의을를은는이가와과로도만")

        for match in re.finditer(_CLAUSE_PATTERN, text):
            start, end = match.span()
            next_char = text[end:end + 1]
            if next_char and next_char in postposition_chars:
                continue

            prev_text = text[:start].rstrip()
            next_text = text[end:].lstrip()

            preceded_like_heading = not prev_text or prev_text[-1] in ".!?)]}"
            followed_like_heading = not next_text or next_text.startswith(("(", "[", "<"))

            if preceded_like_heading or (start == 0) or followed_like_heading:
                results.append(
                    RegexNumberMatch(
                        value=match.group(1),
                        span=match.span(),
                        pattern=_CLAUSE_PATTERN,
                        matched_text=match.group(0),
                    )
                )

        if allow_fallback and not results:
            for match in re.finditer(_CLAUSE_FALLBACK_PATTERN, text, re.MULTILINE):
                results.append(
                    RegexNumberMatch(
                        value=match.group(1),
                        span=match.span(),
                        pattern=_CLAUSE_FALLBACK_PATTERN,
                        matched_text=match.group(0),
                    )
                )

        return results

    def _get_subclause_matches(self, text: str) -> list[RegexNumberMatch]:
        results: list[RegexNumberMatch] = []
        for match in re.finditer(_SUBCLAUSE_PATTERN, text):
            if match.group(1):
                val = match.group(1)
            else:
                enclosed = match.group(2)
                if enclosed is None:
                    continue
                number = _enclosed_number_value(enclosed)
                if number is None:
                    continue
                val = str(number)

            results.append(
                RegexNumberMatch(
                    value=val,
                    span=match.span(),
                    pattern=_SUBCLAUSE_PATTERN,
                    matched_text=match.group(0),
                )
            )
        return results

    def annotate_numbering_signals(self, *, include_table_cells: bool = False) -> DocIR:
        """Sequentially annotate provisional clause/subclause regex signals."""
        scan_items = self._iter_scan_paragraphs(include_table_cells=include_table_cells)
        has_primary_clause = any(re.search(_CLAUSE_PATTERN, text) for _, text in scan_items)
        allow_fallback = not has_primary_clause

        active_clause: str | None = None
        active_subclause: str | None = None

        for paragraph, text in scan_items:
            direct_clause: RegexNumberMatch | None = None
            direct_subclause: RegexNumberMatch | None = None

            if text:
                clause_matches = self._get_clause_matches(text, allow_fallback=allow_fallback)
                if clause_matches:
                    direct_clause = clause_matches[0]
                    active_clause = direct_clause.value
                    active_subclause = None

                    sub_matches = [
                        m for m in self._get_subclause_matches(text)
                        if m.span[0] >= direct_clause.span[1]
                    ]
                    if sub_matches:
                        direct_subclause = sub_matches[0]
                        active_subclause = direct_subclause.value
                else:
                    sub_matches = self._get_subclause_matches(text)
                    if sub_matches and active_clause is not None:
                        direct_subclause = sub_matches[0]
                        active_subclause = direct_subclause.value

            paragraph.parser_signals.regex_clause = direct_clause
            paragraph.parser_signals.regex_subclause = direct_subclause
            paragraph.parser_signals.provisional_clause_no = active_clause
            if active_clause is not None and active_subclause is not None:
                paragraph.parser_signals.provisional_subclause_no = (
                    f"{active_clause}.{active_subclause}"
                )
            else:
                paragraph.parser_signals.provisional_subclause_no = None

        return self

    def apply_review_results(
        self,
        results: list[ParagraphReviewResult],
        *,
        strict: bool = False,
    ) -> DocIR:
        """Apply paragraph-level review/split results in-place."""
        paragraph_map = {paragraph.unit_id: paragraph for paragraph in self.paragraphs}
        for result in results:
            paragraph = paragraph_map.get(result.unit_id)
            if paragraph is None:
                if strict:
                    raise ValueError(f"Unknown paragraph unit_id in review result: {result.unit_id}")
                continue
            paragraph.apply_review_result(result, strict=strict)
        return self

    def recompute_style_signals(self, *, include_table_runs: bool = True) -> DocIR:
        """Recompute paragraph and segment style signals in-place."""
        for paragraph in self.paragraphs:
            paragraph.recompute_style_signal_summary(include_table_runs=include_table_runs)
            if paragraph.segments:
                paragraph._populate_segment_run_spans()
                paragraph.recompute_segment_style_signals()
        return self

    def propagate_semantics_to_runs(self) -> None:
        """Propagate semantic fields from paragraphs into all child runs."""
        for paragraph in self.paragraphs:
            paragraph.propagate_semantics_to_runs()


__all__ = [
    "BBox",
    "DocIR",
    "DocStructureLabel",
    "ParagraphIR",
    "ParagraphReviewResult",
    "ParagraphSegmentIR",
    "RunIR",
    "RegexNumberMatch",
    "ReviewStatus",
    "SegmentRunSpan",
    "SplitOp",
    "SourceType",
    "ParserSignals",
    "TableIR",
    "TableCellIR",
    "TableCellParagraphIR",
]
