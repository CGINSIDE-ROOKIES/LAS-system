"""
edit_assembler — diff-based HWPX run editor
============================================

Overview
--------
LLMs edit ``IRGroup.formatted_str`` without knowing about HWPX run boundaries
or per-run styling.  After the LLM returns its edited text, this module writes
those changes back into the live document while preserving per-run character
styles (bold, italic, colour, etc.).

How it works — "run-safe" editing
----------------------------------
``apply_edit()`` diffs ``article.formatted_str`` against ``edited_text`` using
``difflib.SequenceMatcher``.  Each opcode produced by the differ maps to a
half-open character range ``[i1, i2)`` in the original string.  That range is
then intersected with the ``RunSpan`` list returned by
``IRGroup.run_spans()`` to find which HWPX run(s) it overlaps.

When an opcode falls entirely within a **single run** the text inside that run
is spliced locally (only the changed slice is replaced).  The run's
``charPrIDRef`` (character-property reference — which carries bold, italic,
font, colour, etc.) is untouched.  This is the common case for word-level edits
that respect natural style boundaries.

When an opcode spans **multiple runs** (e.g. a deletion that starts in a plain
run and ends in a bold run), a secondary diff is attempted on the sub-strings
involved.  If the secondary diff still spans multiple runs, the fallback
strategy is applied:

- All new text is assigned to the **first affected run** (its style wins).
- All subsequent affected runs have their text set to ``""`` (the run elements
  are kept alive in the XML — they may carry ``charPrIDRef`` values useful for
  future edits).
- A warning is appended to ``EditResult.warnings``.

Table blocks
------------
Table chunks have IDs containing ``.tbl`` and occupy a contiguous block in
``formatted_str``.  Individual cell runs are not addressable via the run-span
approach, and re-parsing LLM markdown table output is fragile.  Tables are
therefore treated as **read-only**:

- Any opcode whose ``[i1, i2)`` range overlaps a table span is *not applied*.
- The table chunk IDs are collected in ``EditResult.skipped_table_spans``.
- The LLM system prompt should include: "표(markdown table)는 수정하지 마세요."
- If the LLM edits a table anyway the change is silently dropped and logged in
  ``EditResult.warnings``.

Usage example (future LangGraph integration)
--------------------------------------------
::

    from hwpx import HwpxDocument
    from ir import create_ir_dict, article_former
    from edit_assembler import apply_edit

    with HwpxDocument.open("contract.hwpx") as doc:
        articles = article_former(create_ir_dict(doc))

        # … send articles[n].formatted_str to LLM, get edited_text back …

        result = apply_edit(articles[n], edited_text, doc)
        if result.opcodes_applied:
            doc.save_to_path("contract_edited.hwpx")

    print(result)
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from hwpx import HwpxDocument
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from ..las_types import IRGroup, RunSpan


# ---------------------------------------------------------------------------
# Run protocol — both HwpxOxmlRun and docx Run satisfy this
# ---------------------------------------------------------------------------

@runtime_checkable
class EditableRun(Protocol):
    """Minimal interface for a run that can be text-edited."""
    @property
    def text(self) -> str: ...
    @text.setter
    def text(self, value: str) -> None: ...


# ---------------------------------------------------------------------------
# Run resolvers — format-specific chunk_id → run mapping
# ---------------------------------------------------------------------------

def _get_hwpx_run(doc: HwpxDocument, chunk_id: str) -> EditableRun:
    """Resolve ``'s1.p44.r2'`` to an HWPX run."""
    if ".tbl" in chunk_id:
        raise ValueError(f"Table run IDs not supported yet: {chunk_id}")

    parts = chunk_id.split(".")
    s = int(parts[0][1:]) - 1
    p = int(parts[1][1:]) - 1
    r = int(parts[2][1:]) - 1

    return doc.sections[s].paragraphs[p].runs[r]


def _get_docx_run(doc: DocxDocument, chunk_id: str) -> EditableRun:
    """Resolve ``'s1.p44.r2'`` to a python-docx run.

    The paragraph index in the chunk ID counts content blocks (paragraphs
    and tables) in document order — matching how ``docx_ir.py`` assigns
    IDs during parsing.
    """
    if ".tbl" in chunk_id:
        raise ValueError(f"Table run IDs not supported yet: {chunk_id}")

    parts = chunk_id.split(".")
    p = int(parts[1][1:])   # 1-based target
    r = int(parts[2][1:]) - 1

    # Walk content blocks in the same order as docx_ir.export_docx_structured
    block_idx = 0
    for block in doc.iter_inner_content():
        block_idx += 1
        if block_idx == p:
            if isinstance(block, Paragraph):
                return block.runs[r]
            else:
                raise ValueError(
                    f"Block at position {p} is a Table, not a Paragraph: {chunk_id}"
                )

    raise ValueError(f"Paragraph index {p} out of range for document: {chunk_id}")


def get_run_by_id(doc: HwpxDocument | DocxDocument, chunk_id: str) -> EditableRun:
    """Resolve a chunk ID to its run object in either document format.

    IDs use 1-based indexing (``'s1.p44.r2'``).

    Raises:
        ValueError: For table chunk IDs (not supported) or out-of-range indices.
    """
    if isinstance(doc, HwpxDocument):
        return _get_hwpx_run(doc, chunk_id)
    else:
        return _get_docx_run(doc, chunk_id)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

class EditResult(BaseModel):
    """Summary of what :func:`apply_edit` did."""
    opcodes_total: int = 0
    opcodes_applied: int = 0          # non-equal ops
    runs_modified: list[str] = Field(default_factory=list)   # chunk IDs touched
    skipped_table_spans: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _clip_run_spans(
    spans: list[RunSpan],
    i1: int,
    i2: int,
) -> list[RunSpan]:
    """Return the subset of *spans* that overlaps ``[i1, i2)``.

    For zero-width ranges (inserts where ``i1 == i2``), the point is matched
    using inclusive boundaries so that an insert at a run boundary is assigned
    to the **preceding** run (appended) rather than silently dropped.
    """
    is_insert = i1 == i2
    clipped: list[RunSpan] = []
    for span in spans:
        if is_insert:
            if span.end < i1 or span.start > i2:
                continue
        else:
            if span.end <= i1 or span.start >= i2:
                continue
        clipped.append(
            RunSpan(
                # For inserts, preserve the original span start/end so the
                # caller computes correct local offsets within the run.
                start=span.start if is_insert else max(span.start, i1),
                end=span.end if is_insert else min(span.end, i2),
                chunk_id=span.chunk_id,
            )
        )
    # When an insert lands exactly between two adjacent runs, prefer the
    # preceding one (whose end == insert point) so new text is appended to
    # it rather than prepended to the next run.
    if is_insert and len(clipped) > 1:
        preceding = [s for s in clipped if s.end == i1]
        if preceding:
            clipped = preceding[:1]
    return clipped


def _apply_to_run(
    run,
    orig_full: str,
    new_text: str,
    local_start: int,
    local_end: int,
) -> None:
    """Replace ``orig_full[local_start:local_end]`` with *new_text* in *run*."""
    current = run.text or ""
    run.text = current[:local_start] + new_text + current[local_end:]


def _apply_multi_run(
    orig_sub: str,
    new_sub: str,
    spans: list[RunSpan],
    doc: HwpxDocument | DocxDocument,
    result: EditResult,
    *,
    _depth: int = 0,
) -> None:
    """
    Handle an opcode that touches multiple runs.

    Attempts one level of secondary diffing.  If the sub-diff still produces
    multi-run opcodes, falls back to first-run-wins.
    """
    if _depth == 0:
        # Secondary diff on just the affected substring.
        matcher = difflib.SequenceMatcher(None, orig_sub, new_sub, autojunk=False)
        for tag, a1, a2, b1, b2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            sub_spans = _clip_run_spans(spans, a1, a2)
            if not sub_spans:
                continue
            if len(sub_spans) == 1:
                span = sub_spans[0]
                run = get_run_by_id(doc, span.chunk_id)
                local_s = a1 - span.start
                local_e = a2 - span.start
                _apply_to_run(run, run.text or "", new_sub[b1:b2], local_s, local_e)
                if span.chunk_id not in result.runs_modified:
                    result.runs_modified.append(span.chunk_id)
            else:
                # Still multi-run — fall back.
                _apply_multi_run(
                    orig_sub[a1:a2],
                    new_sub[b1:b2],
                    sub_spans,
                    doc,
                    result,
                    _depth=1,
                )
        return

    # Fallback: first-run wins.
    first_run = get_run_by_id(doc, spans[0].chunk_id)
    first_run.text = new_sub
    if spans[0].chunk_id not in result.runs_modified:
        result.runs_modified.append(spans[0].chunk_id)

    for span in spans[1:]:
        run = get_run_by_id(doc, span.chunk_id)
        run.text = ""
        if span.chunk_id not in result.runs_modified:
            result.runs_modified.append(span.chunk_id)

    result.warnings.append(
        f"Multi-run fallback used for opcode spanning "
        f"{[s.chunk_id for s in spans]}: all text assigned to {spans[0].chunk_id}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_edit(
    article: IRGroup,
    edited_text: str,
    doc: HwpxDocument | DocxDocument,
) -> EditResult:
    """
    Apply an LLM-produced edit to the HWPX document in-place.

    The function diffs ``article.formatted_str`` against ``edited_text`` using
    :class:`difflib.SequenceMatcher` and maps each non-equal opcode to the
    HWPX run(s) that own those character positions.  Run styling (bold, italic,
    etc.) is preserved automatically — edits that fall within a single run keep
    that run's ``charPrIDRef`` unchanged.

    Table blocks (chunk IDs containing ``'.tbl'``) are skipped; they are
    reported in :attr:`EditResult.skipped_table_spans` and left untouched in
    the document.

    Args:
        article:     :class:`~las_types.IRGroup` whose ``formatted_str`` was
                     sent to the LLM.
        edited_text: String returned by the LLM (may equal ``formatted_str``).
        doc:         Open :class:`~hwpx.HwpxDocument` to write into.

    Returns:
        :class:`EditResult` with counts and any warnings.

    Raises:
        ValueError: If a chunk ID cannot be resolved in the document.
    """
    result = EditResult()

    orig = article.formatted_str
    all_spans = article.run_spans()

    # Build a quick set of table span ranges so we can detect overlaps.
    table_spans: list[RunSpan] = []
    for i, chunk_id in enumerate(article.ir_chunk_ids):
        if ".tbl" in chunk_id:
            start = article.ir_join[i] if i < len(article.ir_join) else len(orig)
            end = article.ir_join[i + 1] if i + 1 < len(article.ir_join) else len(orig)
            table_spans.append(RunSpan(start=start, end=end, chunk_id=chunk_id))

    matcher = difflib.SequenceMatcher(None, orig, edited_text, autojunk=False)
    opcodes = matcher.get_opcodes()
    result.opcodes_total = len(opcodes)

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue

        result.opcodes_applied += 1

        # Check for table overlap.
        overlapping_tables = [
            t for t in table_spans if t.start < i2 and t.end > i1
        ]
        if overlapping_tables:
            for t in overlapping_tables:
                if t.chunk_id not in result.skipped_table_spans:
                    result.skipped_table_spans.append(t.chunk_id)
            result.warnings.append(
                f"Opcode ({tag}, {i1}:{i2}) overlaps table span(s) "
                f"{[t.chunk_id for t in overlapping_tables]} — skipped"
            )
            continue

        affected = _clip_run_spans(all_spans, i1, i2)
        if not affected:
            continue

        new_sub = edited_text[j1:j2]

        if len(affected) == 1:
            span = affected[0]
            run = get_run_by_id(doc, span.chunk_id)
            local_s = i1 - span.start
            local_e = i2 - span.start
            _apply_to_run(run, run.text or "", new_sub, local_s, local_e)
            if span.chunk_id not in result.runs_modified:
                result.runs_modified.append(span.chunk_id)
        else:
            orig_sub = orig[i1:i2]
            _apply_multi_run(orig_sub, new_sub, affected, doc, result)

    return result
