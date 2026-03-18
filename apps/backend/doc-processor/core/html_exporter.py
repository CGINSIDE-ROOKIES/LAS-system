"""
html_exporter — render IR + StyleMap to styled HTML
=====================================================

Takes :class:`IRGroup` list and a :class:`StyleMap` and produces an HTML
file that preserves text formatting (bold, italic, underline, color,
size, strikethrough, super/subscript) and table styling (borders,
background fill, cell alignment, merged cells).

Font family is excluded by design — it adds cross-platform complexity
with little rendering benefit.

Usage::

    from core.html_exporter import export_html
    html = export_html(ir_groups, style_map, title="계약서")
    Path("out.html").write_text(html, encoding="utf-8")
"""

from __future__ import annotations

import re
from html import escape
from collections import defaultdict

from las_types import (
    IRGroup, IRChunk, StyleMap, RunStyleInfo, ParaStyleInfo, CellStyleInfo,
    ResolvedHighlight, ArticleAnnotations,
)


# ---------------------------------------------------------------------------
# Run-level inline HTML
# ---------------------------------------------------------------------------

def _run_css(style: RunStyleInfo) -> str:
    """Build inline CSS string for a run."""
    parts: list[str] = []
    if style.color:
        parts.append(f"color:{style.color}")
    if style.size_pt:
        parts.append(f"font-size:{style.size_pt:.1f}pt")
    if style.highlight:
        parts.append(f"background-color:{style.highlight}")

    decorations = []
    if style.underline:
        decorations.append("underline")
    if style.strikethrough:
        decorations.append("line-through")
    if decorations:
        parts.append(f"text-decoration:{' '.join(decorations)}")

    return ";".join(parts)


def _apply_highlights(
    text: str,
    run_start: int,
    run_end: int,
    highlights: list[ResolvedHighlight],
) -> str:
    """Apply highlight <mark> tags to *text* based on character ranges.

    *text* is the raw (unescaped) run text.  *run_start*/*run_end* are its
    character offsets within ``formatted_str``.  Returns escaped HTML with
    ``<mark>`` wrappers where highlights overlap.
    """
    if not highlights:
        return escape(text)

    # Collect highlight intervals that overlap this run, clipped to run bounds
    intervals: list[tuple[int, int, str, str]] = []  # (local_start, local_end, color, label)
    for h in highlights:
        if h.end <= run_start or h.start >= run_end:
            continue
        ls = max(0, h.start - run_start)
        le = min(len(text), h.end - run_start)
        if ls < le:
            intervals.append((ls, le, h.color, h.label))

    if not intervals:
        return escape(text)

    # Sort by start, then by end (descending) for nesting
    intervals.sort(key=lambda x: (x[0], -x[1]))

    # Build output by walking through the text
    parts: list[str] = []
    pos = 0
    for ls, le, color, label in intervals:
        if ls > pos:
            parts.append(escape(text[pos:ls]))
        title_attr = f' title="{escape(label)}"' if label else ""
        parts.append(
            f'<mark style="background-color:{escape(color)};padding:1px 2px;border-radius:2px"{title_attr}>'
            f"{escape(text[ls:le])}</mark>"
        )
        pos = max(pos, le)

    if pos < len(text):
        parts.append(escape(text[pos:]))

    return "".join(parts)


def _style_wrap(html: str, style: RunStyleInfo | None) -> str:
    """Apply style tags (bold, italic, etc.) around pre-escaped *html*."""
    if style is None:
        return html

    if style.superscript:
        html = f"<sup>{html}</sup>"
    elif style.subscript:
        html = f"<sub>{html}</sub>"
    if style.bold:
        html = f"<b>{html}</b>"
    if style.italic:
        html = f"<i>{html}</i>"

    css = _run_css(style)
    if css:
        html = f'<span style="{css}">{html}</span>'

    return html


def _escape_whitespace(html: str) -> str:
    """Preserve multiple spaces and tabs as &nbsp; sequences."""
    html = html.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    html = re.sub(r"  +", lambda m: "&nbsp;" * len(m.group(0)), html)
    return html


def _wrap_run(text: str, style: RunStyleInfo | None) -> str:
    """Wrap escaped text in inline tags according to its style."""
    html = escape(text)
    if not html:
        return ""
    html = _escape_whitespace(html)
    return _style_wrap(html, style)


def _wrap_run_highlighted(
    text: str,
    style: RunStyleInfo | None,
    run_start: int,
    run_end: int,
    highlights: list[ResolvedHighlight],
) -> str:
    """Like _wrap_run but with highlight <mark> overlays."""
    html = _apply_highlights(text, run_start, run_end, highlights)
    if not html:
        return ""
    html = _escape_whitespace(html)
    return _style_wrap(html, style)


# ---------------------------------------------------------------------------
# Table HTML
# ---------------------------------------------------------------------------

def _cell_css(style: CellStyleInfo) -> str:
    """Build inline CSS for a table cell."""
    parts: list[str] = []
    if style.background:
        parts.append(f"background-color:{style.background}")
    if style.vertical_align:
        parts.append(f"vertical-align:{style.vertical_align}")
    if style.horizontal_align:
        parts.append(f"text-align:{style.horizontal_align}")

    # Borders: explicit per-side, defaulting to none
    parts.append(f"border-top:{style.border_top or 'none'}")
    parts.append(f"border-bottom:{style.border_bottom or 'none'}")
    parts.append(f"border-left:{style.border_left or 'none'}")
    parts.append(f"border-right:{style.border_right or 'none'}")

    parts.append("padding:4px 6px")
    return ";".join(parts)


def _render_table(
    tbl_root: str,
    chunk_ids: list[str],
    chunks: list[IRChunk],
    style_map: StyleMap,
) -> str:
    """Render a table's IR chunks as an HTML <table>."""
    # Collect cell text with run styling
    # cell_key → list of run HTML fragments
    cell_runs: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)

    for cid, chunk in zip(chunk_ids, chunks):
        if not cid.startswith(tbl_root):
            continue
        m = re.search(r"\.tr(\d+)\.tc(\d+)\.p(\d+)(?:\.r(\d+))?$", cid)
        if not m:
            continue
        tr, tc, cp = int(m.group(1)), int(m.group(2)), int(m.group(3))
        cr = int(m.group(4) or 1)
        run_style = style_map.runs.get(cid)
        html_frag = _wrap_run(chunk.raw_text, run_style)
        cell_runs[(tr, tc, cp)].append((cr, html_frag))

    # Group into cells: (tr, tc) → full HTML content
    cells: dict[tuple[int, int], str] = defaultdict(str)
    for (tr, tc, cp), runs in sorted(cell_runs.items()):
        text = "".join(frag for _, frag in sorted(runs))
        if cells[(tr, tc)]:
            cells[(tr, tc)] += "<br>" + text
        else:
            cells[(tr, tc)] = text

    if not cells:
        return ""

    max_row = max(tr for tr, _ in cells)
    max_col = max(tc for _, tc in cells)

    # Track which cells are covered by rowspan/colspan
    covered: set[tuple[int, int]] = set()
    tbl_info = style_map.tables.get(tbl_root)

    lines = ['<table style="border-collapse:collapse;margin:8px 0">']

    for tr in range(1, max_row + 1):
        lines.append("  <tr>")
        for tc in range(1, max_col + 1):
            if (tr, tc) in covered:
                continue

            cell_key = f"{tbl_root}.tr{tr}.tc{tc}"
            cell_style = style_map.cells.get(cell_key)
            content = cells.get((tr, tc), "")

            attrs: list[str] = []
            if cell_style:
                css = _cell_css(cell_style)
                if css:
                    attrs.append(f'style="{css}"')
                if cell_style.colspan > 1:
                    attrs.append(f'colspan="{cell_style.colspan}"')
                    for c in range(tc + 1, tc + cell_style.colspan):
                        for r in range(tr, tr + cell_style.rowspan):
                            covered.add((r, c))
                if cell_style.rowspan > 1:
                    attrs.append(f'rowspan="{cell_style.rowspan}"')
                    for r in range(tr + 1, tr + cell_style.rowspan):
                        covered.add((r, tc))
            else:
                attrs.append('style="padding:4px 6px"')

            attr_str = " " + " ".join(attrs) if attrs else ""
            lines.append(f"    <td{attr_str}>{content}</td>")
        lines.append("  </tr>")

    lines.append("</table>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Document-level export
# ---------------------------------------------------------------------------

def _para_key(chunk_id: str) -> str:
    """Extract the paragraph portion of a chunk ID (e.g. ``'s1.p5'`` from ``'s1.p5.r2'``)."""
    return re.sub(r"\.r\d+$", "", chunk_id)


def _flush_paragraph(
    run_fragments: list[str],
    para_style: ParaStyleInfo | None,
) -> str:
    """Wrap accumulated run fragments in a <p> tag."""
    content = "".join(run_fragments)
    if not content.strip():
        content = "&nbsp;"  # empty paragraph still takes up vertical space
    css_parts: list[str] = ["margin:0"]
    if para_style and para_style.align:
        css_parts.append(f"text-align:{para_style.align}")
    css = ";".join(css_parts)
    return f'<p style="{css}">{content}</p>\n'


def _render_group(
    group: IRGroup,
    style_map: StyleMap,
    annotations: ArticleAnnotations | None = None,
) -> str:
    """Render a single IRGroup (article) as HTML."""
    parts: list[str] = []
    table_roots_emitted: set[str] = set()
    cur_para: str | None = None
    cur_runs: list[str] = []
    highlights = annotations.resolve(group.formatted_str) if annotations else []

    def flush():
        nonlocal cur_runs, cur_para
        if cur_runs:
            para_style = style_map.paragraphs.get(cur_para) if cur_para else None
            parts.append(_flush_paragraph(cur_runs, para_style))
            cur_runs = []

    for i, (cid, chunk) in enumerate(zip(group.ir_chunk_ids, group.ir_chunks)):
        if ".tbl" in cid:
            tbl_match = re.match(r"^(.*?\.tbl\d+)", cid)
            if not tbl_match:
                continue
            root = tbl_match.group(1)
            if root in table_roots_emitted:
                continue
            table_roots_emitted.add(root)

            flush()
            cur_para = None

            tbl_cids = [c for c in group.ir_chunk_ids if c.startswith(root)]
            tbl_chunks = [
                ch for c, ch in zip(group.ir_chunk_ids, group.ir_chunks)
                if c.startswith(root)
            ]
            parts.append(_render_table(root, tbl_cids, tbl_chunks, style_map))
        else:
            pkey = _para_key(cid)
            if pkey != cur_para:
                flush()
                cur_para = pkey

            run_style = style_map.runs.get(cid)

            if highlights and i < len(group.ir_join):
                run_start = group.ir_join[i]
                run_end = (
                    group.ir_join[i + 1]
                    if i + 1 < len(group.ir_join)
                    else len(group.formatted_str)
                )
                cur_runs.append(_wrap_run_highlighted(
                    chunk.raw_text, run_style, run_start, run_end, highlights,
                ))
            else:
                cur_runs.append(_wrap_run(chunk.raw_text, run_style))

    flush()
    return "".join(parts)


def export_html(
    ir_groups: list[IRGroup],
    style_map: StyleMap,
    *,
    title: str = "Document",
    annotations: dict[int, ArticleAnnotations] | None = None,
) -> str:
    """Export IR groups + style map as a complete HTML document.

    Args:
        ir_groups: List of :class:`IRGroup` from the IR pipeline.
        style_map: :class:`StyleMap` extracted from the source document.
        title: HTML ``<title>`` value.
        annotations: Optional dict mapping group index → :class:`ArticleAnnotations`.
            Highlights are rendered as ``<mark>`` overlays.

    Returns:
        Complete HTML string (UTF-8).
    """
    body_parts: list[str] = []

    for idx, group in enumerate(ir_groups):
        group_ann = annotations.get(idx) if annotations else None
        section_html = _render_group(group, style_map, group_ann)
        if section_html.strip():
            body_parts.append(
                f'<section data-article="{escape(group.article_n)}">\n'
                f"  {section_html}\n"
                f"</section>"
            )

    body = "\n\n".join(body_parts)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
  body {{
    max-width: 800px;
    margin: 2em auto;
    line-height: 1.6;
    color: #1a1a1a;
  }}
  section {{
    margin-bottom: 1.5em;
  }}
  table {{
    border-collapse: collapse;
    margin: 8px 0;
  }}
  mark {{
    padding: 1px 2px;
    border-radius: 2px;
  }}

</style>
</head>
<body>
{body}
</body>
</html>
"""
