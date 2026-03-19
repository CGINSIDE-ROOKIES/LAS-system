from __future__ import annotations

from collections import Counter
from typing import Any
import re

from src.parser.law_parser import _normalize_text_flat, _normalize_text_preserve_structure

IMG_TAG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
IMG_END_TAG_RE = re.compile(r"</img>", re.IGNORECASE)
BOX_VERTICAL_CHARS = "│┃|"
BOX_BORDER_CHARS = "┌┐└┘├┤┬┴┼┏┓┗┛┣┫╋─━═"
HEADER_KEYWORDS = {
    "구분",
    "항목",
    "내용",
    "명칭",
    "비고",
    "기준",
    "등급",
    "종류",
    "코드",
    "번호",
    "금액",
    "일수",
    "업종",
    "질환",
    "색도",
    "글자의 크기",
    "글자의 종류",
    "기재방식",
}


def _extract_image_urls(line: str) -> list[str]:
    return [match.strip() for match in IMG_TAG_RE.findall(line) if match.strip()]


def _clean_api_line(raw_line: str) -> tuple[str, list[str]]:
    line = str(raw_line).replace("\u3000", " ").rstrip()
    image_urls = _extract_image_urls(line)
    line = IMG_TAG_RE.sub("", line)
    line = IMG_END_TAG_RE.sub("", line)
    return line.strip(), image_urls


def _is_box_border_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if any(ch in stripped for ch in "│┃"):
        return False
    if stripped.count("|") >= 2:
        return False
    return any(ch in stripped for ch in BOX_BORDER_CHARS)


# Only treat explicit box-drawing rows as table content. This keeps ordinary aligned text out.
def _is_box_content_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if sum(stripped.count(ch) for ch in "│┃") >= 2:
        return True
    if stripped.count("|") >= 2 and not stripped.startswith("<"):
        return True
    return False


def _is_table_like_line(line: str) -> bool:
    return _is_box_border_line(line) or _is_box_content_line(line)


def _split_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return []

    if "│" in stripped or "┃" in stripped:
        inner = stripped.strip("│┃ ")
        parts = re.split(r"[│┃]", inner)
    else:
        inner = stripped.strip("| ")
        parts = inner.split("|")

    return [re.sub(r"\s+", " ", part).strip() for part in parts]


def _merge_physical_row_lines(physical_rows: list[list[str]]) -> list[str]:
    if not physical_rows:
        return []

    column_count = max(len(row) for row in physical_rows)
    merged = ["" for _ in range(column_count)]

    for row in physical_rows:
        padded = row + [""] * (column_count - len(row))
        for index, cell in enumerate(padded):
            normalized = re.sub(r"\s+", " ", cell).strip()
            if not normalized:
                continue
            if not merged[index]:
                merged[index] = normalized
                continue
            merged[index] = f"{merged[index]}\n{normalized}" if normalized != merged[index] else merged[index]

    return merged


def _remove_empty_columns(rows: list[list[str]]) -> list[list[str]]:
    if not rows:
        return []

    column_count = max(len(row) for row in rows)
    keep_mask: list[bool] = []
    for col_index in range(column_count):
        keep_mask.append(
            any(
                col_index < len(row) and str(row[col_index]).strip() != ""
                for row in rows
            )
        )

    if not any(keep_mask):
        return []

    normalized_rows: list[list[str]] = []
    for row in rows:
        padded = row + [""] * (column_count - len(row))
        normalized_rows.append([cell for keep, cell in zip(keep_mask, padded) if keep])
    return normalized_rows


def _normalize_table_rows(rows: list[list[str]]) -> list[list[str]]:
    normalized_rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not normalized_rows:
        return []

    column_counter = Counter(len(row) for row in normalized_rows if len(row) >= 2)
    if not column_counter:
        return []
    common_columns = max(column_counter.items(), key=lambda item: (item[1], item[0]))[0]

    coerced_rows: list[list[str]] = []
    for row in normalized_rows:
        if len(row) < common_columns:
            row = row + [""] * (common_columns - len(row))
        elif len(row) > common_columns:
            row = row[:common_columns]
        coerced_rows.append(row)

    return _remove_empty_columns(coerced_rows)


def _looks_like_header_row(first_row: list[str], second_row: list[str] | None = None) -> bool:
    filled = [cell.strip() for cell in first_row if str(cell).strip()]
    if not filled:
        return False

    score = 0
    lowered = [cell.lower() for cell in filled]
    if len(set(lowered)) == len(lowered):
        score += 1
    if all(not re.search(r"\d", cell) for cell in filled):
        score += 1
    if any(any(keyword in cell for keyword in HEADER_KEYWORDS) for cell in filled):
        score += 2
    if all(len(cell) <= 40 for cell in filled):
        score += 1

    if second_row:
        second_filled = [cell.strip() for cell in second_row if str(cell).strip()]
        if second_filled and sum(bool(re.search(r"\d", cell)) for cell in second_filled) >= sum(
            bool(re.search(r"\d", cell)) for cell in filled
        ):
            score += 1

    return score >= 3


def _escape_markdown_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", "<br>")


def _render_markdown_table(rows: list[list[str]]) -> dict[str, Any]:
    if not rows:
        return {
            "markdown": None,
            "header_detected": False,
            "header_row": None,
            "data_rows": [],
        }

    column_count = max((len(row) for row in rows), default=0)
    padded_rows = [row + [""] * (column_count - len(row)) for row in rows]

    header_detected = len(padded_rows) >= 2 and _looks_like_header_row(
        padded_rows[0],
        padded_rows[1] if len(padded_rows) > 1 else None,
    )

    if header_detected:
        header_row = [cell or f"열{i + 1}" for i, cell in enumerate(padded_rows[0])]
        data_rows = padded_rows[1:]
    else:
        header_row = [f"열{i + 1}" for i in range(column_count)]
        data_rows = padded_rows

    separator = ["---"] * column_count
    markdown_lines = [
        "| " + " | ".join(_escape_markdown_cell(cell) for cell in header_row) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in data_rows:
        markdown_lines.append("| " + " | ".join(_escape_markdown_cell(cell) for cell in row) + " |")

    return {
        "markdown": "\n".join(markdown_lines).strip(),
        "header_detected": header_detected,
        "header_row": header_row if header_detected else None,
        "data_rows": data_rows,
    }


def _parse_box_table_block(block_lines: list[str], *, table_index: int) -> dict[str, Any] | None:
    physical_rows: list[list[str]] = []
    logical_rows: list[list[str]] = []

    for line in block_lines:
        if _is_box_border_line(line):
            merged = _merge_physical_row_lines(physical_rows)
            if merged:
                logical_rows.append(merged)
            physical_rows = []
            continue

        if _is_box_content_line(line):
            cells = _split_table_cells(line)
            if len(cells) >= 2:
                physical_rows.append(cells)

    merged = _merge_physical_row_lines(physical_rows)
    if merged:
        logical_rows.append(merged)

    normalized_rows = _normalize_table_rows(logical_rows)
    if len(normalized_rows) < 1:
        return None

    column_count = max((len(row) for row in normalized_rows), default=0)
    if column_count < 2:
        return None

    rendered = _render_markdown_table(normalized_rows)
    markdown = rendered.get("markdown")
    if markdown in (None, ""):
        return None

    return {
        "table_index": table_index,
        "page_number": None,
        "row_count": len(normalized_rows),
        "column_count": column_count,
        "header_detected": rendered.get("header_detected"),
        "header_row": rendered.get("header_row"),
        "data_rows": rendered.get("data_rows") or [],
        "rows": normalized_rows,
        "markdown": markdown,
        "source": "api_box_text",
    }


def _iter_segments(lines: list[str]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    text_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _is_table_like_line(line):
            if text_lines:
                segments.append({"type": "text", "lines": text_lines})
                text_lines = []

            block_lines: list[str] = []
            while index < len(lines):
                current = lines[index]
                if _is_table_like_line(current):
                    block_lines.append(current)
                    index += 1
                    continue
                if not current.strip() and index + 1 < len(lines) and _is_table_like_line(lines[index + 1]):
                    index += 1
                    continue
                break

            segments.append({"type": "table_block", "lines": block_lines})
            continue

        text_lines.append(line)
        index += 1

    if text_lines:
        segments.append({"type": "text", "lines": text_lines})
    return segments


def _line_to_markdown(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if re.match(r"^#+\s+", stripped):
        return stripped
    if re.match(r"^\d+\.\s+", stripped):
        return f"## {stripped}"
    if re.match(r"^[가-힣]\.?\s+", stripped):
        return f"### {stripped}"
    if stripped.startswith(("※", "[", "■")):
        return stripped
    return stripped


def parse_api_appendix_text(
    text_raw: str | None,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    if text_raw in (None, ""):
        return {
            "cleaned_lines": [],
            "image_urls": [],
            "structured_tables": [],
            "table_count": 0,
            "markdown_tables": [],
            "table_markdown_text": None,
            "narrative_markdown": None,
            "document_markdown": _normalize_text_preserve_structure(f"# {title}") if title else None,
            "document_markdown_flat": _normalize_text_flat(f"# {title}") if title else None,
        }

    cleaned_lines: list[str] = []
    image_urls: list[str] = []
    for raw_line in str(text_raw).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned_line, urls = _clean_api_line(raw_line)
        image_urls.extend(urls)
        cleaned_lines.append(cleaned_line)

    segments = _iter_segments(cleaned_lines)
    structured_tables: list[dict[str, Any]] = []
    narrative_markdown_lines: list[str] = []
    document_markdown_lines: list[str] = []

    if title:
        document_markdown_lines.append(f"# {title}")
        document_markdown_lines.append("")

    table_number = 0
    for segment in segments:
        if segment.get("type") == "table_block":
            table_number += 1
            table = _parse_box_table_block(segment.get("lines") or [], table_index=table_number - 1)
            if table is None:
                fallback_lines = [line for line in segment.get("lines") or [] if line.strip()]
                if fallback_lines:
                    markdown_block = "\n".join(fallback_lines)
                    document_markdown_lines.append(markdown_block)
                    document_markdown_lines.append("")
                continue

            structured_tables.append(table)
            document_markdown_lines.append(f"### 표 {table_number}")
            document_markdown_lines.append(str(table.get("markdown") or ""))
            document_markdown_lines.append("")
            continue

        for line in segment.get("lines") or []:
            markdown_line = _line_to_markdown(line)
            if markdown_line:
                narrative_markdown_lines.append(markdown_line)
                document_markdown_lines.append(markdown_line)
            elif document_markdown_lines and document_markdown_lines[-1] != "":
                document_markdown_lines.append("")

        if document_markdown_lines and document_markdown_lines[-1] != "":
            document_markdown_lines.append("")
        if narrative_markdown_lines and narrative_markdown_lines[-1] != "":
            narrative_markdown_lines.append("")

    while document_markdown_lines and document_markdown_lines[-1] == "":
        document_markdown_lines.pop()
    while narrative_markdown_lines and narrative_markdown_lines[-1] == "":
        narrative_markdown_lines.pop()

    markdown_tables = [str(table.get("markdown") or "").strip() for table in structured_tables if str(table.get("markdown") or "").strip()]
    table_markdown_sections = []
    for index, table_markdown in enumerate(markdown_tables, start=1):
        table_markdown_sections.append(f"### 표 {index}\n{table_markdown}")

    narrative_markdown = _normalize_text_preserve_structure("\n".join(narrative_markdown_lines))
    document_markdown = _normalize_text_preserve_structure("\n".join(document_markdown_lines))
    table_markdown_text = _normalize_text_preserve_structure("\n\n".join(table_markdown_sections))

    return {
        "cleaned_lines": cleaned_lines,
        "image_urls": list(dict.fromkeys(image_urls)),
        "structured_tables": structured_tables,
        "table_count": len(structured_tables),
        "markdown_tables": markdown_tables,
        "table_markdown_text": table_markdown_text,
        "narrative_markdown": narrative_markdown,
        "document_markdown": document_markdown,
        "document_markdown_flat": _normalize_text_flat(document_markdown),
    }
