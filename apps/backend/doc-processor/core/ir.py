import re
from collections import defaultdict

from tabulate import tabulate
from hwpx import HwpxDocument
from hwpx.tools.exporter import export_markdown_structured

from las_types import IRChunk, IRGroup, NumberMatch


# ---------------------------------------------------------------------------
# Number extraction helpers
# ---------------------------------------------------------------------------

def _enclosed_number_value(ch: str) -> int | None:
    cp = ord(ch)
    if 0x2460 <= cp <= 0x2473:  # ①..⑳
        return cp - 0x2460 + 1
    if 0x2474 <= cp <= 0x2487:  # ⑴..⒇
        return cp - 0x2474 + 1
    if 0x2488 <= cp <= 0x249B:  # ⒈..⒛
        return cp - 0x2488 + 1
    if cp == 0x24EA:  # ⓪
        return 0
    if 0x24F5 <= cp <= 0x24FE:  # ⓵..⓾
        return cp - 0x24F5 + 1
    if 0x2776 <= cp <= 0x277F:  # ❶..❿
        return cp - 0x2776 + 1
    if 0x2780 <= cp <= 0x2789:  # ➀..➉
        return cp - 0x2780 + 1
    if 0x278A <= cp <= 0x2793:  # ➊..➓
        return cp - 0x278A + 1
    return None


def _normalize_enclosed_numbers(text: str) -> str:
    return re.sub(
        r"[\u2460-\u2473\u2474-\u2487\u2488-\u249B\u24EA\u24F5-\u24FE\u2776-\u277F\u2780-\u2789\u278A-\u2793]",
        lambda m: f"({_enclosed_number_value(m.group(0))})",
        text,
    )


def get_article_numbers(text: str) -> list[NumberMatch]:
    """Extract article heading markers like '제N조' from *text*."""
    pattern = r"제\s*(\d+)\s*조"
    results: list[NumberMatch] = []
    postposition_chars = set("에의을를은는이가와과로도만")

    for match in re.finditer(pattern, text):
        start, end = match.span()
        next_char = text[end:end + 1]

        if next_char and next_char in postposition_chars:
            continue

        prev_text = text[:start].rstrip()
        next_text = text[end:].lstrip()

        preceded_like_heading = not prev_text or prev_text[-1] in ".!?)]}"
        followed_like_heading = not next_text or next_text.startswith(("(", "[", "<"))

        if preceded_like_heading or (start == 0) or followed_like_heading:
            results.append(NumberMatch(val=match.group(1), span=match.span()))

    return results


def get_paragraph_numbers(text: str) -> list[NumberMatch]:
    """Extract paragraph markers like '(N)' or Unicode enclosed numbers."""
    pattern = r"\((\d+)\)|([\u2460-\u2473\u2474-\u2487\u2488-\u249B\u24EA\u24F5-\u24FE\u2776-\u277F\u2780-\u2789\u278A-\u2793])"
    results: list[NumberMatch] = []

    for match in re.finditer(pattern, text):
        if match.group(1):
            val = match.group(1)
        else:
            number = _enclosed_number_value(match.group(2))
            if number is None:
                continue
            val = str(number)

        results.append(NumberMatch(val=val, span=match.span()))

    return results


# ---------------------------------------------------------------------------
# IR construction
# ---------------------------------------------------------------------------

def create_ir_dict(doc: HwpxDocument) -> dict[str, IRChunk]:
    """Parse *doc* and return a flat dict of chunk-id → IRChunk."""
    parsed = export_markdown_structured(doc)
    return create_ir_dict_from_mapping(parsed)


def create_ir_dict_from_mapping(parsed: dict[str, str]) -> dict[str, IRChunk]:
    """Build a flat dict of chunk-id → IRChunk from a structured text mapping.

    *parsed* must follow the same ID convention produced by
    ``export_markdown_structured`` (HWPX) or ``export_docx_structured`` (DOCX).
    """
    irs: dict[str, IRChunk] = {}
    active_article_num: str = "-1"
    active_paragraph_num: str | None = None

    for id, text in parsed.items():
        detected_article_nums: list[str] = []
        detected_paragraph_nums: list[str] = []
        splits: list[tuple[int, int]] = []
        section = "uncategorized-table" if "tbl" in id else "uncategorized"

        ex_article = get_article_numbers(text)
        for match in ex_article:
            detected_article_nums.append(match.val)
            splits.append(match.span)

        prefix_end = splits[0][0] if splits else len(text)
        for match in get_paragraph_numbers(text[:prefix_end]):
            if active_article_num != "-1":
                detected_paragraph_nums.append(f"{active_article_num}.{match.val}")

        for i, article_num in enumerate(detected_article_nums):
            seg_start = splits[i][1]
            seg_end = splits[i + 1][0] if i + 1 < len(splits) else len(text)
            for match in get_paragraph_numbers(text[seg_start:seg_end]):
                detected_paragraph_nums.append(f"{article_num}.{match.val}")

        article_nums = detected_article_nums.copy()
        paragraph_nums = detected_paragraph_nums.copy()

        if detected_paragraph_nums and not detected_article_nums and active_article_num != "-1":
            article_nums = [active_article_num]

        if not detected_article_nums and not detected_paragraph_nums:
            if active_article_num != "-1":
                article_nums = [active_article_num]
            if active_paragraph_num is not None:
                paragraph_nums = [active_paragraph_num]

        irs[id] = IRChunk(
            text=text,
            category=section,
            article_n=article_nums,
            paragraph_n=paragraph_nums,
            splits=splits,
        )

        if detected_paragraph_nums:
            active_paragraph_num = detected_paragraph_nums[-1]
            active_article_num = active_paragraph_num.split(".", 1)[0]
        elif detected_article_nums:
            active_article_num = detected_article_nums[-1]
            active_paragraph_num = None

    return irs


# ---------------------------------------------------------------------------
# IR sorting / formatting helpers
# ---------------------------------------------------------------------------

def _sorted_ir_items(irs: dict[str, IRChunk]) -> list[tuple[str, IRChunk]]:
    def sort_key(item: tuple[str, IRChunk]) -> tuple[int, ...]:
        id, _ = item
        return tuple(int(num) for num in re.findall(r"\d+", id))

    return sorted(irs.items(), key=sort_key)


def table_formatter(irs: dict[str, IRChunk]) -> str:
    """Render a single HWPX table's IRChunk entries as a GitHub-flavored markdown table."""
    table_ids = {
        match.group(1)
        for id in irs
        if (match := re.match(r"^(.*?\.tbl\d+)", id))
    }

    assert table_ids, "table_formatter expects table IRChunk entries"
    assert len(table_ids) == 1, "table_formatter expects entries from exactly one table"

    cell_runs: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)
    for id, ir in _sorted_ir_items(irs):
        match = re.search(r"\.tr(\d+)\.tc(\d+)\.p(\d+)(?:\.r(\d+))?$", id)
        if not match:
            continue

        row_num = int(match.group(1))
        col_num = int(match.group(2))
        para_num = int(match.group(3))
        run_num = int(match.group(4) or 1)
        cell_runs[(row_num, col_num, para_num)].append((run_num, ir.text))

    rows: dict[int, dict[int, str]] = defaultdict(dict)
    for (row_num, col_num, para_num), runs in sorted(cell_runs.items()):
        text = "".join(run_text for run_num, run_text in sorted(runs)).strip()
        if para_num > 1 and rows[row_num].get(col_num):
            rows[row_num][col_num] += "<br>" + text
        else:
            rows[row_num][col_num] = text

    max_col = max(max(cols) for cols in rows.values())
    table = [
        [rows[row_num].get(col_num, "") for col_num in range(1, max_col + 1)]
        for row_num in sorted(rows)
    ]
    return tabulate(table, tablefmt="github")


# ---------------------------------------------------------------------------
# Article-level formatting
# ---------------------------------------------------------------------------

def _export_article_to_markdown(article: IRGroup) -> str:
    """Build ``article.formatted_str`` from its IRChunks and return it."""
    if not article.ir_chunks or not article.ir_chunk_ids:
        return _normalize_enclosed_numbers(article.formatted_str)

    parts: list[str] = []
    table_roots_emitted: set[str] = set()
    table_root_start: dict[str, int] = {}   # root → pre-strip char position
    join_points: list[int] = []             # one entry per IRchunk_ids element

    for id, ir in zip(article.ir_chunk_ids, article.ir_chunks):
        pos = sum(len(p) for p in parts)

        if ".tbl" in id:
            table_root = re.match(r"^(.*?\.tbl\d+)", id)
            if not table_root:
                join_points.append(pos)
                continue
            root = table_root.group(1)
            if root in table_roots_emitted:
                join_points.append(table_root_start[root])
                continue
            table_root_start[root] = pos
            join_points.append(pos)
            table_subset = {
                cid: cir
                for cid, cir in zip(article.ir_chunk_ids, article.ir_chunks)
                if cid.startswith(root)
            }
            rendered = "\n" + table_formatter(table_subset) + "\n"
            parts.append(rendered)
            table_roots_emitted.add(root)
        else:
            join_points.append(pos)
            parts.append(ir.text)

    combined = "".join(parts)
    strip_offset = len(combined) - len(combined.lstrip())

    # Adjust IRjoin for strip offset
    article.ir_join = [max(0, p - strip_offset) for p in join_points]

    article.formatted_str = combined.strip()
    return _normalize_enclosed_numbers(article.formatted_str)


def ir_grouper(irs: dict[str, IRChunk]) -> list[IRGroup]:
    """Group *irs* by article number and return one :class:`IRGroup` per article."""
    articles: list[IRGroup] = []
    current: IRGroup | None = None

    for id, ir in _sorted_ir_items(irs):
        article_n = ir.article_n[0] if ir.article_n else "-1"
        if current is None or current.article_n != article_n:
            current = IRGroup(article_n=article_n)
            articles.append(current)

        current.ir_chunk_ids.append(id)
        current.ir_chunks.append(ir)

    for article in articles:
        article.formatted_str = _export_article_to_markdown(article)

    return articles
