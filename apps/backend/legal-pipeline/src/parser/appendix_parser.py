from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Literal
import re

from src.common.appendix_scope import appendix_exclusion_reason
from src.parser.appendix_api_markdown import parse_api_appendix_text
from src.common.io_utils import _safe_filename, _write_json
from src.common.payload_utils import _first_non_empty
from src.parser.law_parser import (
    _looks_metadata_like,
    _normalize_text_flat,
    _normalize_text_preserve_structure,
    _normalize_title,
    _normalize_title_raw,
    get_law_root,
)

AppendixType = Literal[
    "appendix_document",
    "table_appendix",
    "metadata_only",
]

FORM_TITLE_TOKENS = (
    "서식",
    "신청서",
    "신고서",
    "인가서",
    "승인서",
    "명령서",
    "증명서",
    "대장",
    "명부",
    "통지서",
    "계약서",
    "해지서",
    "청구서",
    "인허증",
    "신청",
)

FORM_TEXT_TOKENS = (
    "접수번호",
    "처리기간",
    "신청인",
    "피신청인",
    "주민등록번호",
    "사업장명",
    "대표자명",
    "전화번호",
    "첨부서류",
    "서명 또는 인",
    "대리인",
)

TABLE_STRUCTURE_TOKENS = "┌┐└┘├┤┬┴┼│─━┏┓┗┛┃"
TABLE_TITLE_TOKENS = (
    "표",
    "분류",
    "보상",
    "기준",
    "산정",
    "일람",
    "규격",
    "양식",
    "기재사항",
    "직종",
    "질환",
    "업종",
    "등급",
    "금액",
)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _walk_text_fragments(node: Any) -> Iterable[str]:
    if node in (None, ""):
        return
    if isinstance(node, str):
        yield node
        return
    if isinstance(node, list):
        for item in node:
            yield from _walk_text_fragments(item)
        return
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_text_fragments(value)
        return

    text = str(node).strip()
    if text:
        yield text


def _extract_text_lines(value: Any) -> list[str]:
    lines: list[str] = []

    for fragment in _walk_text_fragments(value):
        for raw_line in str(fragment).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.rstrip()
            if line or (lines and lines[-1] != ""):
                lines.append(line)

    while lines and lines[-1] == "":
        lines.pop()

    return lines


def _extract_text_raw(value: Any) -> str | None:
    lines = _extract_text_lines(value)
    if not lines:
        return None
    return _normalize_text_preserve_structure("\n".join(lines))


def _normalize_relative_link(value: Any) -> str | None:
    text = _normalize_text_flat(value)
    if text in (None, ""):
        return None
    return text


def _normalize_filename_list(value: Any) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for item in _as_list(value):
        text = _normalize_text_flat(item)
        if text in (None, ""):
            continue
        if text in seen:
            continue
        seen.add(text)
        results.append(text)

    return results


def _count_table_signals(text: str | None) -> int:
    if text in (None, ""):
        return 0

    raw = str(text)
    signal_count = sum(raw.count(token) for token in TABLE_STRUCTURE_TOKENS)
    signal_count += sum(1 for line in raw.splitlines() if line.count("│") >= 2)
    signal_count += sum(1 for line in raw.splitlines() if line.count("|") >= 2)
    return signal_count


def _count_form_signals(title: str | None, text: str | None) -> int:
    title_text = title or ""
    body_text = text or ""

    score = sum(1 for token in FORM_TITLE_TOKENS if token in title_text)
    score += sum(1 for token in FORM_TEXT_TOKENS if token in body_text)
    return score


def _line_column_count(line: str) -> int:
    stripped = str(line).strip()
    if not stripped:
        return 0

    if "│" in stripped:
        cells = [cell.strip() for cell in re.split(r"\s*│\s*", stripped.strip("│ ")) if cell.strip()]
        return len(cells)

    if stripped.count("|") >= 2:
        cells = [cell.strip() for cell in re.split(r"\s*\|\s*", stripped.strip("| ")) if cell.strip()]
        return len(cells)

    cells = [cell.strip() for cell in re.split(r"\s{2,}", stripped) if cell.strip()]
    return len(cells) if len(cells) >= 2 else 0


def _stable_table_layout_score(text: str | None) -> dict[str, int]:
    if text in (None, ""):
        return {"common_columns": 0, "supporting_line_count": 0}

    lines = [line for line in str(text).splitlines() if line.strip()]
    column_counter: Counter[int] = Counter(
        count for count in (_line_column_count(line) for line in lines) if count >= 2
    )
    if not column_counter:
        return {"common_columns": 0, "supporting_line_count": 0}

    common_columns, supporting_line_count = max(
        column_counter.items(),
        key=lambda item: (item[1], item[0]),
    )
    return {
        "common_columns": int(common_columns),
        "supporting_line_count": int(supporting_line_count),
    }


def _has_tableish_title(title: str | None) -> bool:
    normalized = _normalize_text_flat(title) or ""
    return any(token in normalized for token in TABLE_TITLE_TOKENS)


def _looks_table_like_strict(title: str | None, text: str | None) -> bool:
    if text in (None, ""):
        return False

    raw_text = str(text)
    table_signal_count = _count_table_signals(raw_text)
    lines = [line for line in raw_text.splitlines() if line.strip()]
    boxed_lines = sum(1 for line in lines if line.count("│") >= 2 or line.count("|") >= 2)
    layout_score = _stable_table_layout_score(raw_text)
    common_columns = int(layout_score.get("common_columns") or 0)
    supporting_line_count = int(layout_score.get("supporting_line_count") or 0)

    if table_signal_count >= 8:
        return True
    if boxed_lines >= 2:
        return True
    if common_columns >= 3 and supporting_line_count >= 3:
        return True
    if common_columns >= 2 and supporting_line_count >= 3 and table_signal_count >= 2:
        return True
    if common_columns >= 2 and supporting_line_count >= 4 and _has_tableish_title(title):
        return True

    return False


def _classify_appendix_type(
    appendix_kind: str | None,
    appendix_key: str | None,
    title: str | None,
    text_raw: str | None,
    *,
    api_table_count: int = 0,
) -> AppendixType:
    del appendix_kind, appendix_key  # kept for future diagnostics
    title_text = title or ""
    if text_raw in (None, ""):
        return "metadata_only"

    if _looks_metadata_like(title_text, text_raw):
        return "metadata_only"

    if api_table_count > 0:
        return "table_appendix"

    if _looks_table_like_strict(title_text, text_raw):
        return "table_appendix"

    return "appendix_document"


def _extract_law_meta(
    payload: dict[str, Any],
    law_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    law_root = get_law_root(payload)
    basic_info = law_root.get("기본정보") if isinstance(law_root.get("기본정보"), dict) else {}

    kind_value = _first_non_empty(
        basic_info.get("법종구분", {}) if isinstance(basic_info.get("법종구분"), dict) else {},
        "content",
        "법종구분명",
        "법령구분명",
    )

    ministry_value = _first_non_empty(
        basic_info.get("소관부처", {}) if isinstance(basic_info.get("소관부처"), dict) else {},
        "content",
        "소관부처명",
    )

    return {
        "law_name": (law_ref or {}).get("law_name")
        or _first_non_empty(law_root, "법령명한글", "법령명")
        or _first_non_empty(basic_info, "법령명_한글", "법령명한글", "법령명"),
        "law_id": (law_ref or {}).get("law_id")
        or _first_non_empty(law_root, "법령ID", "law_id")
        or _first_non_empty(basic_info, "법령ID", "law_id"),
        "mst": (law_ref or {}).get("mst")
        or _first_non_empty(law_root, "법령일련번호", "mst")
        or _first_non_empty(basic_info, "MST", "mst", "법령일련번호"),
        "ef_yd": (law_ref or {}).get("ef_yd")
        or _first_non_empty(law_root, "시행일자", "ef_yd")
        or _first_non_empty(basic_info, "시행일자", "ef_yd"),
        "kind_name": (law_ref or {}).get("kind_name")
        or _first_non_empty(law_root, "법령구분명", "법종구분명", "kind_name")
        or kind_value,
        "ministry_name": (law_ref or {}).get("ministry_name")
        or _first_non_empty(law_root, "소관부처명", "ministry_name")
        or ministry_value,
        "classified_level": (law_ref or {}).get("classified_level"),
        "scope_source": (law_ref or {}).get("scope_source"),
        "promulgation_date": (law_ref or {}).get("promulgation_date")
        or _first_non_empty(basic_info, "공포일자", "promulgation_date"),
        "promulgation_no": (law_ref or {}).get("promulgation_no")
        or _first_non_empty(basic_info, "공포번호", "promulgation_no"),
    }


def _extract_appendix_units(law_root: dict[str, Any]) -> list[dict[str, Any]]:
    appendix_container = law_root.get("별표")
    if not isinstance(appendix_container, dict):
        return []

    units = appendix_container.get("별표단위")
    return [unit for unit in _as_list(units) if isinstance(unit, dict)]


def _build_processing_policy(
    *,
    appendix_type: AppendixType,
    has_text: bool,
    has_pdf_asset: bool,
    has_image_asset: bool,
    has_download_link: bool,
    has_api_tables: bool,
) -> dict[str, Any]:
    pdf_fallback = has_pdf_asset or has_download_link
    ocr_fallback = has_image_asset or pdf_fallback

    if appendix_type == "metadata_only":
        default_primary = "metadata_only"
        recommended = "metadata_only_keep_for_reference"
    elif appendix_type == "appendix_document":
        default_primary = "api_document_markdown" if has_text else "pdf_text"
        recommended = (
            "use_api_document_markdown_as_primary"
            if has_text
            else "reextract_pdf_text_if_available"
        )
    else:
        default_primary = "api_table_markdown" if has_api_tables else "api_text_clean"
        recommended = (
            "use_api_table_markdown_as_primary_then_reextract_pdf_if_needed"
            if has_api_tables
            else "use_api_text_clean_then_reextract_pdf_if_layout_needed"
        )

    return {
        "default_primary": default_primary,
        "pdf_fallback": pdf_fallback,
        "ocr_fallback": ocr_fallback,
        "recommended_next_step": recommended,
    }


def parse_appendix_bundle(
    payload: dict[str, Any],
    law_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    law_root = get_law_root(payload)
    law_meta = _extract_law_meta(payload, law_ref=law_ref)

    records: list[dict[str, Any]] = []
    excluded_records: list[dict[str, Any]] = []

    for unit in _extract_appendix_units(law_root):
        appendix_key = _normalize_text_flat(_first_non_empty(unit, "별표키", "appendix_key"))
        appendix_kind = _normalize_title(
            _first_non_empty(unit, "별표구분", "appendix_kind")
        )
        title_raw = _normalize_title_raw(
            _first_non_empty(unit, "별표제목", "별표제목문자열", "appendix_title")
        )
        title = _normalize_title(title_raw) or title_raw or "별표"

        exclusion_reason = appendix_exclusion_reason(
            appendix_kind,
            title,
            appendix_key,
        )
        if exclusion_reason is not None:
            excluded_records.append(
                {
                    **law_meta,
                    "appendix_key": appendix_key,
                    "appendix_kind": appendix_kind,
                    "appendix_title_raw": title_raw,
                    "appendix_title": title,
                    "excluded_reason": exclusion_reason,
                }
            )
            continue

        text_raw = _extract_text_raw(_first_non_empty(unit, "별표내용", "appendix_text"))
        text_clean = _normalize_text_flat(text_raw)
        text_lines = _extract_text_lines(_first_non_empty(unit, "별표내용", "appendix_text"))
        api_markdown = parse_api_appendix_text(
            text_raw,
            title=title,
        )

        file_download_link = _normalize_relative_link(
            _first_non_empty(unit, "별표서식파일링크", "appendix_download_link")
        )
        pdf_download_link = _normalize_relative_link(
            _first_non_empty(unit, "별표서식PDF파일링크", "appendix_pdf_download_link")
        )
        pdf_file_name = _normalize_text_flat(
            _first_non_empty(unit, "별표PDF파일명", "appendix_pdf_file_name")
        )
        hwp_file_name = _normalize_text_flat(
            _first_non_empty(unit, "별표HWP파일명", "appendix_hwp_file_name")
        )
        image_file_names = _normalize_filename_list(
            _first_non_empty(unit, "별표이미지파일명", "appendix_image_file_names")
        )

        appendix_type = _classify_appendix_type(
            appendix_kind=appendix_kind,
            appendix_key=appendix_key,
            title=title,
            text_raw=text_raw,
            api_table_count=int(api_markdown.get("table_count") or 0),
        )

        has_text = text_clean not in (None, "")
        has_pdf_asset = pdf_download_link is not None or pdf_file_name is not None
        has_image_asset = bool(image_file_names or api_markdown.get("image_urls"))
        has_download_link = file_download_link is not None
        has_api_tables = bool(api_markdown.get("table_count"))

        processing_policy = _build_processing_policy(
            appendix_type=appendix_type,
            has_text=has_text,
            has_pdf_asset=has_pdf_asset,
            has_image_asset=has_image_asset,
            has_download_link=has_download_link,
            has_api_tables=has_api_tables,
        )

        record_id = "::".join(
            [
                "appendix",
                str(law_meta.get("law_name") or law_meta.get("law_id") or "unknown"),
                str(appendix_key or title or len(records)),
            ]
        )

        records.append(
            {
                "id": record_id,
                **law_meta,
                "appendix_key": appendix_key,
                "appendix_no": _normalize_text_flat(
                    _first_non_empty(unit, "별표번호", "appendix_no")
                ),
                "appendix_branch_no": _normalize_text_flat(
                    _first_non_empty(unit, "별표가지번호", "appendix_branch_no")
                ),
                "appendix_effective_date": _normalize_text_flat(
                    _first_non_empty(unit, "별표시행일자", "appendix_effective_date")
                ),
                "appendix_kind": appendix_kind or "별표",
                "appendix_type": appendix_type,
                "appendix_title_raw": title_raw,
                "appendix_title": title,
                "api_text_raw": text_raw,
                "api_text": text_clean,
                "api_text_lines": text_lines,
                "api_text_line_count": len([line for line in text_lines if line.strip()]),
                "api_image_urls": api_markdown.get("image_urls") or [],
                "api_markdown_tables": api_markdown.get("markdown_tables") or [],
                "api_table_markdown_text": api_markdown.get("table_markdown_text"),
                "api_structured_tables": api_markdown.get("structured_tables") or [],
                "api_table_count": int(api_markdown.get("table_count") or 0),
                "api_narrative_markdown": api_markdown.get("narrative_markdown"),
                "api_document_markdown": api_markdown.get("document_markdown"),
                "api_document_markdown_flat": api_markdown.get("document_markdown_flat"),
                "table_signal_count": _count_table_signals(text_raw),
                "form_signal_count": _count_form_signals(title, text_raw),
                "has_substantive_text": has_text,
                "has_table_markup": appendix_type == "table_appendix" or bool(api_markdown.get("table_count")),
                "is_default_serving_candidate": appendix_type == "appendix_document",
                "download_assets": {
                    "file_download_link": file_download_link,
                    "pdf_download_link": pdf_download_link,
                    "pdf_file_name": pdf_file_name,
                    "hwp_file_name": hwp_file_name,
                    "image_file_names": image_file_names,
                    "api_image_urls": api_markdown.get("image_urls") or [],
                },
                "processing_policy": processing_policy,
            }
        )

    appendix_type_counts = Counter(record["appendix_type"] for record in records)
    excluded_reason_counts = Counter(record["excluded_reason"] for record in excluded_records)

    return {
        **law_meta,
        "appendix_scope": "별표_only",
        "appendix_count": len(records),
        "appendix_type_counts": dict(appendix_type_counts),
        "excluded_appendix_count": len(excluded_records),
        "excluded_reason_counts": dict(excluded_reason_counts),
        "excluded_appendix_records": excluded_records,
        "processing_policy": {
            "default_primary": "api_markdown_or_clean",
            "secondary": "pdf_reextract_if_needed",
            "tertiary": "ocr_or_vision_if_needed",
        },
        "appendix_records": records,
    }


def save_parsed_appendix_bundle(
    appendix_bundle: dict[str, Any],
    save_dir: str | Path,
) -> Path:
    law_name = str(appendix_bundle.get("law_name") or "unnamed")
    output_path = Path(save_dir) / f"{_safe_filename(law_name)}__parsed_appendix.json"
    _write_json(output_path, appendix_bundle)
    return output_path
