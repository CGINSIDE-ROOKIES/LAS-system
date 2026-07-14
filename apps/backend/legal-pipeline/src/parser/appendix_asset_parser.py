from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

try:
    from pypdf import PdfReader
except ModuleNotFoundError:  # pragma: no cover - optional in offline test env
    PdfReader = None  # type: ignore[assignment]

try:
    import pdfplumber
except ModuleNotFoundError:  # pragma: no cover - optional in offline test env
    pdfplumber = None  # type: ignore[assignment]

from src.common.io_utils import _read_json, _safe_filename, _write_json
from src.parser.appendix_parser import _count_table_signals
from src.parser.law_parser import _looks_table_like, _normalize_text_flat, _normalize_text_preserve_structure


SUPPORTED_EXTRACTION_KINDS = {"pdf"}

PDFPLUMBER_TABLE_STRATEGIES: tuple[dict[str, Any], ...] = (
    {
        "name": "lines",
        "table_settings": {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 3,
        },
    },
    {
        "name": "lines_strict",
        "table_settings": {
            "vertical_strategy": "lines_strict",
            "horizontal_strategy": "lines_strict",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 3,
        },
    },
    {
        "name": "mixed",
        "table_settings": {
            "vertical_strategy": "lines",
            "horizontal_strategy": "text",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 5,
            "min_words_vertical": 2,
            "min_words_horizontal": 1,
            "text_x_tolerance": 3,
            "text_y_tolerance": 3,
        },
    },
    {
        "name": "text",
        "table_settings": {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_tolerance": 3,
            "join_tolerance": 3,
            "intersection_tolerance": 5,
            "min_words_vertical": 2,
            "min_words_horizontal": 1,
            "text_x_tolerance": 3,
            "text_y_tolerance": 3,
        },
    },
)

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
    "disease",
    "name",
    "title",
    "description",
    "code",
    "remarks",
    "type",
    "grade",
    "amount",
}


def _score_text_quality(raw_text: str | None) -> int:
    if raw_text in (None, ""):
        return 0
    text = str(raw_text)
    line_count = len([line for line in text.splitlines() if line.strip()])
    char_count = len(text)
    table_signal_count = _count_table_signals(text)
    return char_count + (line_count * 2) + (table_signal_count * 4)


def _normalize_table_cell(value: Any) -> str:
    if value in (None, ""):
        return ""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    normalized_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            normalized_lines.append(line)

    return "\n".join(normalized_lines).strip()


def _remove_empty_table_columns(rows: list[list[str]]) -> list[list[str]]:
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
        padded_row = row + [""] * (column_count - len(row))
        normalized_rows.append([cell for keep, cell in zip(keep_mask, padded_row) if keep])

    return normalized_rows


def _normalize_extracted_table(raw_rows: list[list[Any]]) -> list[list[str]]:
    if not isinstance(raw_rows, list):
        return []

    normalized_rows: list[list[str]] = []
    max_columns = 0

    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        row = [_normalize_table_cell(cell) for cell in raw_row]
        if any(cell for cell in row):
            normalized_rows.append(row)
            max_columns = max(max_columns, len(row))

    if not normalized_rows or max_columns == 0:
        return []

    padded_rows = [row + [""] * (max_columns - len(row)) for row in normalized_rows]
    trimmed_rows = _remove_empty_table_columns(padded_rows)
    return [row for row in trimmed_rows if any(cell for cell in row)]


def _count_non_empty_cells(rows: list[list[str]]) -> int:
    return sum(1 for row in rows for cell in row if str(cell).strip())


def _sum_cell_characters(rows: list[list[str]]) -> int:
    return sum(len(str(cell).strip()) for row in rows for cell in row if str(cell).strip())


def _score_table_rows(rows: list[list[str]]) -> int:
    if not rows:
        return 0

    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    non_empty_cells = _count_non_empty_cells(rows)
    char_count = _sum_cell_characters(rows)

    score = (non_empty_cells * 8) + (row_count * 4) + (column_count * 12) + min(char_count, 4000) // 20
    if row_count < 2:
        score -= 20
    if column_count < 2:
        score -= 10
    return score


def _looks_like_header_row(first_row: list[str], second_row: list[str] | None = None) -> bool:
    filled = [cell.strip() for cell in first_row if str(cell).strip()]
    if not filled:
        return False

    score = 0
    lowered_cells = [cell.lower() for cell in filled]

    if len(set(lowered_cells)) == len(lowered_cells):
        score += 1
    if all(not re.search(r"\d", cell) for cell in filled):
        score += 1
    if any(any(keyword in cell for keyword in HEADER_KEYWORDS) for cell in lowered_cells):
        score += 2
    if all(len(cell) <= 40 for cell in filled):
        score += 1

    if second_row:
        second_filled = [cell.strip() for cell in second_row if str(cell).strip()]
        if second_filled:
            if sum(bool(re.search(r"\d", cell)) for cell in second_filled) >= sum(bool(re.search(r"\d", cell)) for cell in filled):
                score += 1
            if max((len(cell) for cell in second_filled), default=0) > max((len(cell) for cell in filled), default=0):
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


def _extract_tables_from_pdfplumber_page(page: Any, *, page_number: int) -> dict[str, Any]:
    strategy_summaries: list[dict[str, Any]] = []
    best_strategy_result: dict[str, Any] | None = None

    for strategy_config in PDFPLUMBER_TABLE_STRATEGIES:
        strategy_name = str(strategy_config.get("name") or "unknown")
        table_settings = dict(strategy_config.get("table_settings") or {})

        extracted_tables: list[dict[str, Any]] = []
        extraction_error: str | None = None
        try:
            raw_tables = page.extract_tables(table_settings=table_settings) or []
        except Exception as exc:  # pragma: no cover - extractor failure branch
            raw_tables = []
            extraction_error = str(exc)

        for table_index, raw_table in enumerate(raw_tables):
            normalized_rows = _normalize_extracted_table(raw_table)
            quality_score = _score_table_rows(normalized_rows)
            if not normalized_rows or quality_score < 30:
                continue

            markdown_payload = _render_markdown_table(normalized_rows)
            column_count = max((len(row) for row in normalized_rows), default=0)
            row_count = len(normalized_rows)
            non_empty_cell_count = _count_non_empty_cells(normalized_rows)
            char_count = _sum_cell_characters(normalized_rows)

            extracted_tables.append(
                {
                    "table_index": table_index,
                    "page_number": page_number,
                    "strategy": strategy_name,
                    "row_count": row_count,
                    "column_count": column_count,
                    "non_empty_cell_count": non_empty_cell_count,
                    "char_count": char_count,
                    "quality_score": quality_score,
                    "header_detected": markdown_payload.get("header_detected"),
                    "header_row": markdown_payload.get("header_row"),
                    "data_rows": markdown_payload.get("data_rows") or [],
                    "rows": normalized_rows,
                    "markdown": markdown_payload.get("markdown"),
                }
            )

        total_score = sum(int(table.get("quality_score") or 0) for table in extracted_tables)
        strategy_summary = {
            "strategy": strategy_name,
            "table_count": len(extracted_tables),
            "total_score": total_score,
            "error_message": extraction_error,
        }
        strategy_summaries.append(strategy_summary)

        current_result = {
            "strategy": strategy_name,
            "tables": extracted_tables,
            "table_count": len(extracted_tables),
            "total_score": total_score,
        }
        if best_strategy_result is None or (
            current_result["total_score"],
            current_result["table_count"],
        ) > (
            best_strategy_result["total_score"],
            best_strategy_result["table_count"],
        ):
            best_strategy_result = current_result

    if best_strategy_result is None:
        best_strategy_result = {
            "strategy": None,
            "tables": [],
            "table_count": 0,
            "total_score": 0,
        }

    return {
        "page_number": page_number,
        "selected_strategy": best_strategy_result.get("strategy"),
        "tables": best_strategy_result.get("tables") or [],
        "table_count": int(best_strategy_result.get("table_count") or 0),
        "total_score": int(best_strategy_result.get("total_score") or 0),
        "strategy_summaries": strategy_summaries,
    }


def _render_table_bundle_markdown(tables: list[dict[str, Any]]) -> dict[str, Any]:
    markdown_tables: list[str] = []
    sections: list[str] = []

    for index, table in enumerate(tables, start=1):
        markdown = str(table.get("markdown") or "").strip()
        if not markdown:
            continue
        page_number = table.get("page_number")
        heading = f"### 표 {index}"
        if page_number not in (None, ""):
            heading = f"{heading} (페이지 {page_number})"
        sections.append(f"{heading}\n{markdown}")
        markdown_tables.append(markdown)

    return {
        "markdown_tables": markdown_tables,
        "table_markdown_text": "\n\n".join(section for section in sections if section).strip() or None,
    }


def _extract_pdf_with_pypdf(path: Path) -> dict[str, Any]:
    if PdfReader is None:
        return {
            "engine": "pypdf",
            "status": "engine_unavailable",
            "page_count": 0,
            "raw_text": None,
        }

    reader = PdfReader(str(path))
    page_texts: list[str] = []

    for page in reader.pages:
        extracted = ""
        try:
            extracted = (page.extract_text(extraction_mode="layout") or "").strip()
        except TypeError:  # pragma: no cover - older pypdf fallback
            extracted = (page.extract_text() or "").strip()
        page_texts.append(extracted)

    raw_text = "\n\n".join(text for text in page_texts if text)
    return {
        "engine": "pypdf",
        "status": "success" if raw_text else "empty_text",
        "page_count": len(reader.pages),
        "raw_text": raw_text or None,
    }


def _extract_pdf_with_pdfplumber(path: Path) -> dict[str, Any]:
    if pdfplumber is None:
        return {
            "engine": "pdfplumber",
            "status": "engine_unavailable",
            "page_count": 0,
            "raw_text": None,
            "tables": [],
            "table_count": 0,
            "markdown_tables": [],
            "table_markdown_text": None,
            "has_structured_tables": False,
            "table_extraction_summary": [],
            "table_row_count": 0,
            "table_cell_count": 0,
        }

    with pdfplumber.open(path) as pdf:
        page_texts: list[str] = []
        all_tables: list[dict[str, Any]] = []
        table_extraction_summary: list[dict[str, Any]] = []

        for page_number, page in enumerate(pdf.pages, start=1):
            page_texts.append((page.extract_text() or "").strip())
            page_table_result = _extract_tables_from_pdfplumber_page(page, page_number=page_number)
            all_tables.extend(page_table_result.get("tables") or [])
            table_extraction_summary.append(
                {
                    "page_number": page_number,
                    "selected_strategy": page_table_result.get("selected_strategy"),
                    "table_count": page_table_result.get("table_count"),
                    "total_score": page_table_result.get("total_score"),
                    "strategy_summaries": page_table_result.get("strategy_summaries") or [],
                }
            )

    raw_text = "\n\n".join(text for text in page_texts if text)
    table_markdown_payload = _render_table_bundle_markdown(all_tables)

    return {
        "engine": "pdfplumber",
        "status": "success" if raw_text or all_tables else "empty_text",
        "page_count": len(page_texts),
        "raw_text": raw_text or None,
        "tables": all_tables,
        "table_count": len(all_tables),
        "markdown_tables": table_markdown_payload.get("markdown_tables") or [],
        "table_markdown_text": table_markdown_payload.get("table_markdown_text"),
        "has_structured_tables": bool(all_tables),
        "table_extraction_summary": table_extraction_summary,
        "table_row_count": sum(int(table.get("row_count") or 0) for table in all_tables),
        "table_cell_count": sum(int(table.get("non_empty_cell_count") or 0) for table in all_tables),
    }


def extract_text_from_pdf(path: str | Path) -> dict[str, Any]:
    pdf_path = Path(path)
    candidates: list[dict[str, Any]] = []
    pdfplumber_candidate: dict[str, Any] | None = None

    for extractor in (_extract_pdf_with_pypdf, _extract_pdf_with_pdfplumber):
        try:
            result = extractor(pdf_path)
        except Exception as exc:  # pragma: no cover - extractor failure branch
            candidates.append(
                {
                    "engine": extractor.__name__,
                    "status": "extract_error",
                    "page_count": 0,
                    "raw_text": None,
                    "error_message": str(exc),
                }
            )
            continue

        result["quality_score"] = _score_text_quality(result.get("raw_text"))
        candidates.append(result)
        if result.get("engine") == "pdfplumber":
            pdfplumber_candidate = result

    best = max(candidates, key=lambda item: int(item.get("quality_score") or 0), default=None)
    if not best:
        return {
            "extraction_status": "extract_error",
            "extraction_engine": None,
            "page_count": 0,
            "text_raw": None,
            "text": None,
            "char_count": 0,
            "line_count": 0,
            "table_signal_count": 0,
            "has_table_markup": False,
            "has_structured_tables": False,
            "table_count": 0,
            "table_row_count": 0,
            "table_cell_count": 0,
            "markdown_tables": [],
            "table_markdown_text": None,
            "table_markdown_flat": None,
            "tables": [],
            "table_extraction_engine": None,
            "table_extraction_summary": [],
            "error_message": "No PDF extractor available",
        }

    raw_text = _normalize_text_preserve_structure(best.get("raw_text"))
    text = _normalize_text_flat(best.get("raw_text"))
    line_count = len([line for line in (raw_text or "").splitlines() if line.strip()])

    table_markdown_text = _normalize_text_preserve_structure(
        (pdfplumber_candidate or {}).get("table_markdown_text")
    )
    markdown_tables = [
        _normalize_text_preserve_structure(table)
        for table in ((pdfplumber_candidate or {}).get("markdown_tables") or [])
        if table not in (None, "")
    ]
    tables = list((pdfplumber_candidate or {}).get("tables") or [])
    has_structured_tables = bool((pdfplumber_candidate or {}).get("has_structured_tables"))

    return {
        "extraction_status": "success" if raw_text or table_markdown_text else str(best.get("status") or "empty_text"),
        "extraction_engine": best.get("engine"),
        "page_count": int(best.get("page_count") or 0),
        "text_raw": raw_text,
        "text": text,
        "char_count": len(raw_text or text or ""),
        "line_count": line_count,
        "table_signal_count": _count_table_signals(raw_text),
        "has_table_markup": _looks_table_like(raw_text),
        "has_structured_tables": has_structured_tables,
        "table_count": int((pdfplumber_candidate or {}).get("table_count") or 0),
        "table_row_count": int((pdfplumber_candidate or {}).get("table_row_count") or 0),
        "table_cell_count": int((pdfplumber_candidate or {}).get("table_cell_count") or 0),
        "markdown_tables": markdown_tables,
        "table_markdown_text": table_markdown_text,
        "table_markdown_flat": _normalize_text_flat(table_markdown_text),
        "tables": tables,
        "table_extraction_engine": (pdfplumber_candidate or {}).get("engine"),
        "table_extraction_summary": (pdfplumber_candidate or {}).get("table_extraction_summary") or [],
        "error_message": best.get("error_message"),
    }


def _score_pdf_asset(asset: dict[str, Any]) -> int:
    return int(asset.get("char_count") or 0) + (int(asset.get("table_count") or 0) * 30)


def _score_structured_table_asset(asset: dict[str, Any]) -> int:
    return (
        (int(asset.get("table_count") or 0) * 100)
        + (int(asset.get("table_cell_count") or 0) * 12)
        + len(str(asset.get("table_markdown_text") or ""))
    )


def _best_text_result(
    *,
    source: str,
    reason: str,
    text_raw: str | None,
    text: str | None,
    asset_id: Any,
    asset_local_path: Any,
    table_markdown_text: str | None = None,
    structured_tables: list[dict[str, Any]] | None = None,
    table_count: int = 0,
) -> dict[str, Any]:
    return {
        "best_text_source": source,
        "best_text_reason": reason,
        "best_text_raw": text_raw,
        "best_text": text,
        "best_asset_id": asset_id,
        "best_asset_local_path": asset_local_path,
        "best_table_markdown_text": table_markdown_text,
        "best_structured_tables": structured_tables or [],
        "best_table_count": table_count,
        "has_structured_tables": bool(structured_tables),
    }


def _choose_best_text(
    *,
    appendix_type: str,
    api_text_raw: str | None,
    api_text: str | None,
    api_document_markdown: str | None,
    api_table_markdown_text: str | None,
    api_structured_tables: list[dict[str, Any]] | None,
    extracted_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_api_raw = _normalize_text_preserve_structure(api_text_raw or api_text)
    normalized_api = _normalize_text_flat(api_text or api_text_raw)
    normalized_api_document_markdown = _normalize_text_preserve_structure(api_document_markdown)
    normalized_api_table_markdown = _normalize_text_preserve_structure(api_table_markdown_text)
    normalized_api_document_flat = _normalize_text_flat(api_document_markdown)
    normalized_api_table_flat = _normalize_text_flat(api_table_markdown_text)
    structured_api_tables = [table for table in (api_structured_tables or []) if isinstance(table, dict)]
    api_char_count = len(normalized_api_document_markdown or normalized_api_raw or normalized_api or "")

    successful_pdf_assets = [
        asset
        for asset in extracted_assets
        if asset.get("asset_kind") == "pdf"
        and asset.get("extraction_status") == "success"
        and (asset.get("text_raw") not in (None, "") or asset.get("table_markdown_text") not in (None, ""))
    ]
    best_pdf_asset = max(successful_pdf_assets, key=_score_pdf_asset, default=None)
    best_structured_table_asset = max(
        [
            asset
            for asset in successful_pdf_assets
            if asset.get("has_structured_tables") and asset.get("table_markdown_text") not in (None, "")
        ],
        key=_score_structured_table_asset,
        default=None,
    )

    if appendix_type == "table_appendix":
        if normalized_api_table_markdown and structured_api_tables:
            return _best_text_result(
                source="api_table_markdown",
                reason="api_box_table_markdown_extracted",
                text_raw=normalized_api_table_markdown,
                text=normalized_api_table_flat or _normalize_text_flat(normalized_api_table_markdown),
                asset_id=None,
                asset_local_path=None,
                table_markdown_text=normalized_api_table_markdown,
                structured_tables=structured_api_tables,
                table_count=len(structured_api_tables),
            )
        if best_structured_table_asset is not None:
            return _best_text_result(
                source="pdf_table_markdown",
                reason="structured_pdf_tables_extracted",
                text_raw=best_structured_table_asset.get("table_markdown_text"),
                text=best_structured_table_asset.get("table_markdown_flat")
                or _normalize_text_flat(best_structured_table_asset.get("table_markdown_text")),
                asset_id=best_structured_table_asset.get("asset_id"),
                asset_local_path=best_structured_table_asset.get("local_path"),
                table_markdown_text=best_structured_table_asset.get("table_markdown_text"),
                structured_tables=list(best_structured_table_asset.get("tables") or []),
                table_count=int(best_structured_table_asset.get("table_count") or 0),
            )
        if best_pdf_asset is not None:
            return _best_text_result(
                source="pdf_text",
                reason="api_table_structure_unavailable_pdf_used_as_fallback",
                text_raw=best_pdf_asset.get("text_raw"),
                text=best_pdf_asset.get("text"),
                asset_id=best_pdf_asset.get("asset_id"),
                asset_local_path=best_pdf_asset.get("local_path"),
            )
        if normalized_api_document_markdown or normalized_api_raw or normalized_api:
            return _best_text_result(
                source="api_markdown" if normalized_api_document_markdown else "api_text",
                reason="fallback_to_api_text_or_markdown",
                text_raw=normalized_api_document_markdown or normalized_api_raw,
                text=normalized_api_document_flat or normalized_api,
                asset_id=None,
                asset_local_path=None,
            )
        return _best_text_result(
            source="none",
            reason="no_text_available",
            text_raw=None,
            text=None,
            asset_id=None,
            asset_local_path=None,
        )

    if appendix_type == "appendix_document":
        if normalized_api_document_markdown:
            return _best_text_result(
                source="api_markdown",
                reason="api_document_markdown_kept_as_primary",
                text_raw=normalized_api_document_markdown,
                text=normalized_api_document_flat or _normalize_text_flat(normalized_api_document_markdown),
                asset_id=None,
                asset_local_path=None,
            )
        if best_pdf_asset is not None and not normalized_api_raw:
            return _best_text_result(
                source="pdf_text",
                reason="api_text_missing_pdf_available",
                text_raw=best_pdf_asset.get("text_raw"),
                text=best_pdf_asset.get("text"),
                asset_id=best_pdf_asset.get("asset_id"),
                asset_local_path=best_pdf_asset.get("local_path"),
            )
        if best_pdf_asset is not None and int(best_pdf_asset.get("char_count") or 0) >= max(api_char_count + 120, int(api_char_count * 1.25)):
            return _best_text_result(
                source="pdf_text",
                reason="pdf_text_substantially_richer_than_api_text",
                text_raw=best_pdf_asset.get("text_raw"),
                text=best_pdf_asset.get("text"),
                asset_id=best_pdf_asset.get("asset_id"),
                asset_local_path=best_pdf_asset.get("local_path"),
            )
        if normalized_api_raw or normalized_api:
            return _best_text_result(
                source="api_text",
                reason="api_text_kept_as_primary",
                text_raw=normalized_api_raw,
                text=normalized_api,
                asset_id=None,
                asset_local_path=None,
            )
        if best_pdf_asset is not None:
            return _best_text_result(
                source="pdf_text",
                reason="fallback_to_pdf_text",
                text_raw=best_pdf_asset.get("text_raw"),
                text=best_pdf_asset.get("text"),
                asset_id=best_pdf_asset.get("asset_id"),
                asset_local_path=best_pdf_asset.get("local_path"),
            )

    if normalized_api_document_markdown:
        return _best_text_result(
            source="api_markdown",
            reason="metadata_or_api_markdown_fallback",
            text_raw=normalized_api_document_markdown,
            text=normalized_api_document_flat or _normalize_text_flat(normalized_api_document_markdown),
            asset_id=None,
            asset_local_path=None,
        )

    if normalized_api_raw or normalized_api:
        return _best_text_result(
            source="api_text",
            reason="metadata_or_api_fallback",
            text_raw=normalized_api_raw,
            text=normalized_api,
            asset_id=None,
            asset_local_path=None,
        )

    if best_pdf_asset is not None:
        return _best_text_result(
            source="pdf_text",
            reason="metadata_fallback_to_pdf_text",
            text_raw=best_pdf_asset.get("text_raw"),
            text=best_pdf_asset.get("text"),
            asset_id=best_pdf_asset.get("asset_id"),
            asset_local_path=best_pdf_asset.get("local_path"),
        )

    return _best_text_result(
        source="none",
        reason="no_text_available",
        text_raw=None,
        text=None,
        asset_id=None,
        asset_local_path=None,
    )


def parse_appendix_asset_bundle(raw_asset_bundle: dict[str, Any]) -> dict[str, Any]:
    appendix_asset_records = raw_asset_bundle.get("appendix_asset_records")
    if not isinstance(appendix_asset_records, list):
        appendix_asset_records = []

    parsed_records: list[dict[str, Any]] = []
    extracted_asset_count = 0
    successful_extraction_count = 0
    structured_table_count = 0
    structured_table_asset_count = 0

    for appendix_record in appendix_asset_records:
        if not isinstance(appendix_record, dict):
            continue

        asset_candidates = appendix_record.get("asset_candidates")
        if not isinstance(asset_candidates, list):
            asset_candidates = []

        parsed_assets: list[dict[str, Any]] = []
        for asset in asset_candidates:
            if not isinstance(asset, dict):
                continue

            parsed_asset = {
                "asset_id": asset.get("asset_id"),
                "asset_role": asset.get("asset_role"),
                "asset_kind": asset.get("asset_kind"),
                "declared_file_name": asset.get("declared_file_name"),
                "resolved_file_name": asset.get("resolved_file_name"),
                "local_path": asset.get("local_path"),
                "download_status": asset.get("download_status"),
                "content_type": asset.get("content_type"),
                "byte_size": asset.get("byte_size"),
                "sha256": asset.get("sha256"),
                "source_url": asset.get("source_url"),
                "resolved_url": asset.get("resolved_url"),
            }

            local_path_value = asset.get("local_path")
            if asset.get("download_status") not in {"downloaded", "skipped_existing"} or local_path_value in (None, ""):
                parsed_asset.update(
                    {
                        "extraction_status": "not_downloaded",
                        "extraction_engine": None,
                        "page_count": 0,
                        "text_raw": None,
                        "text": None,
                        "char_count": 0,
                        "line_count": 0,
                        "table_signal_count": 0,
                        "has_table_markup": False,
                        "has_structured_tables": False,
                        "table_count": 0,
                        "table_row_count": 0,
                        "table_cell_count": 0,
                        "markdown_tables": [],
                        "table_markdown_text": None,
                        "table_markdown_flat": None,
                        "tables": [],
                        "table_extraction_engine": None,
                        "table_extraction_summary": [],
                        "error_message": asset.get("error_message"),
                    }
                )
                parsed_assets.append(parsed_asset)
                continue

            extracted_asset_count += 1
            asset_kind = str(asset.get("asset_kind") or "binary")
            if asset_kind not in SUPPORTED_EXTRACTION_KINDS:
                parsed_asset.update(
                    {
                        "extraction_status": "unsupported_kind",
                        "extraction_engine": None,
                        "page_count": 0,
                        "text_raw": None,
                        "text": None,
                        "char_count": 0,
                        "line_count": 0,
                        "table_signal_count": 0,
                        "has_table_markup": False,
                        "has_structured_tables": False,
                        "table_count": 0,
                        "table_row_count": 0,
                        "table_cell_count": 0,
                        "markdown_tables": [],
                        "table_markdown_text": None,
                        "table_markdown_flat": None,
                        "tables": [],
                        "table_extraction_engine": None,
                        "table_extraction_summary": [],
                        "error_message": None,
                    }
                )
                parsed_assets.append(parsed_asset)
                continue

            extraction_result = extract_text_from_pdf(str(local_path_value))
            if extraction_result.get("extraction_status") == "success":
                successful_extraction_count += 1
            if extraction_result.get("has_structured_tables"):
                structured_table_asset_count += 1
                structured_table_count += int(extraction_result.get("table_count") or 0)
            parsed_asset.update(extraction_result)
            parsed_assets.append(parsed_asset)

        best_text = _choose_best_text(
            appendix_type=str(appendix_record.get("appendix_type") or "appendix_document"),
            api_text_raw=appendix_record.get("api_text_raw"),
            api_text=appendix_record.get("api_text"),
            api_document_markdown=appendix_record.get("api_document_markdown"),
            api_table_markdown_text=appendix_record.get("api_table_markdown_text"),
            api_structured_tables=appendix_record.get("api_structured_tables") or [],
            extracted_assets=parsed_assets,
        )

        parsed_records.append(
            {
                "appendix_id": appendix_record.get("appendix_id"),
                "appendix_key": appendix_record.get("appendix_key"),
                "appendix_no": appendix_record.get("appendix_no"),
                "appendix_type": appendix_record.get("appendix_type"),
                "appendix_title": appendix_record.get("appendix_title"),
                "law_name": appendix_record.get("law_name"),
                "law_id": appendix_record.get("law_id"),
                "mst": appendix_record.get("mst"),
                "ef_yd": appendix_record.get("ef_yd"),
                "kind_name": appendix_record.get("kind_name"),
                "api_text_raw": appendix_record.get("api_text_raw"),
                "api_text": appendix_record.get("api_text"),
                "api_document_markdown": appendix_record.get("api_document_markdown"),
                "api_document_markdown_flat": appendix_record.get("api_document_markdown_flat"),
                "api_table_markdown_text": appendix_record.get("api_table_markdown_text"),
                "api_markdown_tables": appendix_record.get("api_markdown_tables") or [],
                "api_structured_tables": appendix_record.get("api_structured_tables") or [],
                "api_table_count": appendix_record.get("api_table_count") or 0,
                "has_substantive_text": appendix_record.get("has_substantive_text"),
                "processing_policy": appendix_record.get("processing_policy", {}),
                "downloaded_asset_count": sum(
                    1
                    for asset in parsed_assets
                    if asset.get("download_status") in {"downloaded", "skipped_existing"}
                ),
                "extractable_asset_count": sum(
                    1 for asset in parsed_assets if asset.get("asset_kind") in SUPPORTED_EXTRACTION_KINDS
                ),
                "successful_extraction_count": sum(
                    1 for asset in parsed_assets if asset.get("extraction_status") == "success"
                ),
                "structured_table_asset_count": sum(
                    1 for asset in parsed_assets if asset.get("has_structured_tables")
                ),
                "structured_table_count": sum(int(asset.get("table_count") or 0) for asset in parsed_assets),
                **best_text,
                "assets": parsed_assets,
            }
        )

    return {
        "law_name": raw_asset_bundle.get("law_name"),
        "law_id": raw_asset_bundle.get("law_id"),
        "mst": raw_asset_bundle.get("mst"),
        "ef_yd": raw_asset_bundle.get("ef_yd"),
        "appendix_count": len(parsed_records),
        "parsed_asset_bundle_count": len(parsed_records),
        "downloaded_asset_count": sum(
            int(record.get("downloaded_asset_count") or 0) for record in parsed_records
        ),
        "extractable_asset_count": sum(
            int(record.get("extractable_asset_count") or 0) for record in parsed_records
        ),
        "successful_extraction_count": sum(
            int(record.get("successful_extraction_count") or 0) for record in parsed_records
        ),
        "structured_table_asset_count": sum(
            int(record.get("structured_table_asset_count") or 0) for record in parsed_records
        ),
        "structured_table_count": sum(
            int(record.get("structured_table_count") or 0) for record in parsed_records
        ),
        "raw_asset_candidate_count": raw_asset_bundle.get("asset_candidate_count"),
        "raw_downloaded_count": raw_asset_bundle.get("downloaded_count"),
        "asset_extractions_attempted": extracted_asset_count,
        "asset_extractions_successful": successful_extraction_count,
        "asset_structured_table_extractions": structured_table_asset_count,
        "asset_structured_table_count": structured_table_count,
        "appendix_asset_records": parsed_records,
    }


def save_parsed_appendix_asset_bundle(
    parsed_asset_bundle: dict[str, Any],
    *,
    save_dir: str | Path,
) -> Path:
    law_name = str(parsed_asset_bundle.get("law_name") or "unnamed")
    output_path = Path(save_dir) / _safe_filename(law_name) / f"{_safe_filename(law_name)}__appendix_assets.parsed.json"
    _write_json(output_path, parsed_asset_bundle)
    return output_path


def _iter_raw_asset_bundle_paths(raw_asset_base_dir: str | Path) -> Iterable[Path]:
    return sorted(Path(raw_asset_base_dir).rglob("*__appendix_assets.raw.json"))


def normalize_appendix_asset_bundles(
    *,
    raw_asset_base_dir: str | Path = "data/raw/01_current_law_appendix_assets",
    save_dir: str | Path = "data/normalized/01_current_law_appendix_assets",
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []

    bundle_count = 0
    appendix_count = 0
    downloaded_asset_count = 0
    successful_extraction_count = 0
    structured_table_asset_count = 0
    structured_table_count = 0

    for path in _iter_raw_asset_bundle_paths(raw_asset_base_dir):
        raw_asset_bundle = _read_json(path)
        parsed_asset_bundle = parse_appendix_asset_bundle(raw_asset_bundle)
        saved_path = save_parsed_appendix_asset_bundle(
            parsed_asset_bundle,
            save_dir=save_dir,
        )

        summaries.append(
            {
                "law_name": parsed_asset_bundle.get("law_name"),
                "appendix_count": parsed_asset_bundle.get("appendix_count"),
                "downloaded_asset_count": parsed_asset_bundle.get("downloaded_asset_count"),
                "successful_extraction_count": parsed_asset_bundle.get("successful_extraction_count"),
                "structured_table_asset_count": parsed_asset_bundle.get("structured_table_asset_count"),
                "structured_table_count": parsed_asset_bundle.get("structured_table_count"),
                "bundle_path": str(saved_path),
                "source_raw_asset_bundle_path": str(path),
            }
        )

        bundle_count += 1
        appendix_count += int(parsed_asset_bundle.get("appendix_count") or 0)
        downloaded_asset_count += int(parsed_asset_bundle.get("downloaded_asset_count") or 0)
        successful_extraction_count += int(parsed_asset_bundle.get("successful_extraction_count") or 0)
        structured_table_asset_count += int(parsed_asset_bundle.get("structured_table_asset_count") or 0)
        structured_table_count += int(parsed_asset_bundle.get("structured_table_count") or 0)

    summary = {
        "bundle_count": bundle_count,
        "appendix_count": appendix_count,
        "downloaded_asset_count": downloaded_asset_count,
        "successful_extraction_count": successful_extraction_count,
        "structured_table_asset_count": structured_table_asset_count,
        "structured_table_count": structured_table_count,
        "bundles": summaries,
    }

    _write_json(Path(save_dir) / "appendix_asset_parse_summary.json", summary)
    return summary
