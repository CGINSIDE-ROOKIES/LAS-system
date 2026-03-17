from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.common.io_utils import _read_json, _write_json
from src.export.jsonl_builder import write_jsonl


APPENDIX_TYPE_LABELS = {
    "appendix_document": "appendix_document",
    "table_appendix": "table_appendix",
    "form_appendix": "form_appendix",
    "metadata_only": "metadata_only",
}


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_structure(text: str) -> str:
    normalized_lines: list[str] = []
    previous_blank = False

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", raw_line).strip()
        if not line:
            if normalized_lines and not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(line)
        previous_blank = False

    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()

    return "\n".join(normalized_lines).strip()


def _select_text(
    record: dict[str, Any],
    *,
    preserve_structure: bool,
    asset_record: dict[str, Any] | None = None,
) -> str:
    candidate_values: list[Any] = []

    if asset_record is not None and str(asset_record.get("best_text_source") or "") not in {"", "none", "api_text"}:
        candidate_values.extend(
            [
                asset_record.get("best_text_raw") if preserve_structure else asset_record.get("best_text"),
                asset_record.get("best_text") if preserve_structure else asset_record.get("best_text_raw"),
            ]
        )

    candidate_values.extend(
        [
            record.get("api_text_raw") if preserve_structure else record.get("api_text"),
            record.get("api_text") if preserve_structure else record.get("api_text_raw"),
        ]
    )

    for value in candidate_values:
        if value in (None, ""):
            continue
        text = str(value)
        return _normalize_structure(text) if preserve_structure else _normalize_space(text)

    return ""


def _resolve_text_source(asset_record: dict[str, Any] | None) -> str:
    if asset_record is None:
        return "api_text"
    source = str(asset_record.get("best_text_source") or "api_text").strip() or "api_text"
    return source


def _render_prefixed_text(prefix: str, text: str) -> str:
    prefix = prefix.strip()
    text = text.strip()

    if not prefix:
        return text
    if not text:
        return prefix

    lines = text.splitlines()
    if len(lines) == 1:
        return f"{prefix} {lines[0]}".strip()

    indent = " " * (len(prefix) + 1)
    rendered = [f"{prefix} {lines[0]}".rstrip()]
    rendered.extend(f"{indent}{line}" if line else "" for line in lines[1:])
    return "\n".join(rendered).strip()


def _split_long_line(line: str, max_chars: int) -> list[str]:
    line = line.strip()
    if not line:
        return []
    if len(line) <= max_chars:
        return [line]

    parts: list[str] = []
    remaining = line

    while len(remaining) > max_chars:
        split_candidates = [
            remaining.rfind(" ", 0, max_chars),
            remaining.rfind(",", 0, max_chars),
            remaining.rfind("·", 0, max_chars),
        ]
        split = max(split_candidates)
        if split <= max_chars // 2:
            split = max_chars

        parts.append(remaining[:split].rstrip())
        remaining = remaining[split:].lstrip()

    if remaining:
        parts.append(remaining)

    return parts


def _split_structured_segment(segment: str, max_chars: int) -> list[str]:
    segment = _normalize_structure(segment)
    if not segment:
        return []
    if len(segment) <= max_chars:
        return [segment]

    results: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for raw_line in segment.splitlines():
        line_parts = _split_long_line(raw_line, max_chars) or [""]

        for line in line_parts:
            separator_len = 1 if current_lines else 0
            next_len = current_len + separator_len + len(line)
            if current_lines and next_len > max_chars:
                results.append("\n".join(current_lines).strip())
                current_lines = []
                current_len = 0
                separator_len = 0

            current_lines.append(line)
            current_len += separator_len + len(line)

    if current_lines:
        results.append("\n".join(current_lines).strip())

    return [result for result in results if result]


def _tail_overlap_by_lines(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""

    selected: list[str] = []
    current_len = 0

    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue

        separator_len = 1 if selected else 0
        next_len = current_len + separator_len + len(stripped)
        if selected and next_len > max_chars:
            break

        selected.append(stripped)
        current_len = next_len
        if current_len >= max_chars:
            break

    return "\n".join(reversed(selected)).strip()


def _chunk_text(
    text: str,
    max_chars: int = 1200,
    overlap: int = 150,
    *,
    preserve_structure: bool = True,
) -> list[str]:
    text = _normalize_structure(text) if preserve_structure else _normalize_space(text)
    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    if not preserve_structure:
        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = min(len(text), start + max_chars)
            if end < len(text):
                split_candidates = [
                    text.rfind("\n", start, end),
                    text.rfind(". ", start, end),
                    text.rfind("。", start, end),
                    text.rfind(" ", start, end),
                ]
                split = max(split_candidates)
                if split > start + (max_chars // 2):
                    end = split + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            if end >= len(text):
                break

            start = max(0, end - overlap)

        return chunks

    segments: list[str] = []
    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if not block:
            continue
        segments.extend(_split_structured_segment(block, max_chars))

    if not segments:
        return []

    chunks: list[str] = []
    current = ""

    for segment in segments:
        candidate = segment if not current else f"{current}\n\n{segment}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            overlap_seed = _tail_overlap_by_lines(current, overlap)
        else:
            overlap_seed = ""

        if overlap_seed and len(f"{overlap_seed}\n\n{segment}") <= max_chars:
            current = f"{overlap_seed}\n\n{segment}"
        else:
            current = segment

    if current:
        chunks.append(current)

    return chunks


def _iter_appendix_bundle_paths(normalized_appendix_base_dir: str | Path) -> Iterable[Path]:
    base_dir = Path(normalized_appendix_base_dir)
    return sorted(base_dir.rglob("*__parsed_appendix.json"))


def _iter_appendix_records(normalized_appendix_base_dir: str | Path) -> Iterable[tuple[Path, dict[str, Any], dict[str, Any]]]:
    for path in _iter_appendix_bundle_paths(normalized_appendix_base_dir):
        bundle = _read_json(path)
        records = bundle.get("appendix_records", [])
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict):
                yield path, bundle, record


def _iter_appendix_asset_bundle_paths(normalized_appendix_asset_base_dir: str | Path) -> Iterable[Path]:
    return sorted(Path(normalized_appendix_asset_base_dir).rglob("*__appendix_assets.parsed.json"))


def _load_appendix_asset_index(
    normalized_appendix_asset_base_dir: str | Path | None,
) -> dict[str, dict[str, Any]]:
    if normalized_appendix_asset_base_dir is None:
        return {}

    index: dict[str, dict[str, Any]] = {}
    for path in _iter_appendix_asset_bundle_paths(normalized_appendix_asset_base_dir):
        bundle = _read_json(path)
        records = bundle.get("appendix_asset_records", [])
        if not isinstance(records, list):
            continue

        for record in records:
            if not isinstance(record, dict):
                continue
            appendix_id = record.get("appendix_id")
            if appendix_id in (None, ""):
                continue

            indexed_record = dict(record)
            indexed_record["normalized_asset_bundle_path"] = str(path)
            index[str(appendix_id)] = indexed_record

    return index


def _build_appendix_text(
    record: dict[str, Any],
    *,
    preserve_structure: bool,
    asset_record: dict[str, Any] | None = None,
) -> str:
    appendix_title = str(record.get("appendix_title") or "별표").strip()
    appendix_kind = str(record.get("appendix_kind") or "").strip()
    appendix_type = str(record.get("appendix_type") or "appendix_document").strip()
    text = _select_text(record, preserve_structure=preserve_structure, asset_record=asset_record)
    text_source = _resolve_text_source(asset_record)

    lines: list[str] = []
    if record.get("law_name"):
        lines.append(f"법령명: {record['law_name']}")
    if record.get("kind_name"):
        lines.append(f"법령종류: {record['kind_name']}")
    lines.append(f"구성요소: {APPENDIX_TYPE_LABELS.get(appendix_type, appendix_type)}")
    if appendix_kind:
        lines.append(f"별표구분: {appendix_kind}")
    if record.get("appendix_no"):
        lines.append(f"별표번호: {record['appendix_no']}")
    lines.append(_render_prefixed_text("별표제목:", appendix_title))
    if asset_record is not None and text_source != "api_text":
        lines.append(f"텍스트소스: {text_source}")
    if text:
        lines.append(text)

    return "\n".join(line for line in lines if line).strip()


def build_appendix_raw_records(
    normalized_appendix_base_dir: str | Path = "data/normalized/01_current_law_appendix",
    *,
    normalized_appendix_asset_base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    asset_index = _load_appendix_asset_index(normalized_appendix_asset_base_dir)

    for path, bundle, record in _iter_appendix_records(normalized_appendix_base_dir):
        asset_record = asset_index.get(str(record.get("id") or ""))
        raw_record = {
            "id": record.get("id"),
            "doc_type": "law_appendix_raw",
            "source_group": "01_current_law_appendix",
            "law_name": record.get("law_name"),
            "law_id": record.get("law_id"),
            "mst": record.get("mst"),
            "ef_yd": record.get("ef_yd"),
            "kind_name": record.get("kind_name"),
            "ministry_name": record.get("ministry_name"),
            "appendix_key": record.get("appendix_key"),
            "appendix_no": record.get("appendix_no"),
            "appendix_branch_no": record.get("appendix_branch_no"),
            "appendix_effective_date": record.get("appendix_effective_date"),
            "appendix_kind": record.get("appendix_kind"),
            "appendix_type": record.get("appendix_type"),
            "appendix_title": record.get("appendix_title"),
            "api_text_raw": record.get("api_text_raw"),
            "api_text": record.get("api_text"),
            "api_text_line_count": record.get("api_text_line_count"),
            "table_signal_count": record.get("table_signal_count"),
            "form_signal_count": record.get("form_signal_count"),
            "has_substantive_text": record.get("has_substantive_text"),
            "has_table_markup": record.get("has_table_markup"),
            "is_default_serving_candidate": record.get("is_default_serving_candidate"),
            "download_assets": record.get("download_assets", {}),
            "processing_policy": record.get("processing_policy", {}),
            "best_text_source": asset_record.get("best_text_source") if asset_record is not None else "api_text",
            "best_text_reason": asset_record.get("best_text_reason") if asset_record is not None else None,
            "asset_text_available": bool(asset_record and asset_record.get("best_text_source") not in {None, "", "none"}),
            "downloaded_asset_count": asset_record.get("downloaded_asset_count") if asset_record is not None else 0,
            "successful_extraction_count": asset_record.get("successful_extraction_count") if asset_record is not None else 0,
            "best_asset_local_path": asset_record.get("best_asset_local_path") if asset_record is not None else None,
            "normalized_asset_bundle_path": asset_record.get("normalized_asset_bundle_path") if asset_record is not None else None,
            "source_file_path": str(path),
        }
        records.append(raw_record)

    return records


def build_appendix_clean_records(
    normalized_appendix_base_dir: str | Path = "data/normalized/01_current_law_appendix",
    max_chars: int = 1200,
    overlap: int = 150,
    *,
    include_types: Sequence[str] = ("appendix_document",),
    preserve_structure: bool = True,
    normalized_appendix_asset_base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    allowed_types = set(include_types)
    asset_index = _load_appendix_asset_index(normalized_appendix_asset_base_dir)

    for path, bundle, record in _iter_appendix_records(normalized_appendix_base_dir):
        appendix_type = str(record.get("appendix_type") or "")
        if appendix_type not in allowed_types:
            continue

        asset_record = asset_index.get(str(record.get("id") or ""))
        selected_text = _select_text(
            record,
            preserve_structure=preserve_structure,
            asset_record=asset_record,
        )
        if not selected_text:
            continue

        text = _build_appendix_text(
            record,
            preserve_structure=preserve_structure,
            asset_record=asset_record,
        )
        chunks = _chunk_text(
            text,
            max_chars=max_chars,
            overlap=overlap,
            preserve_structure=preserve_structure,
        )

        for chunk_index, chunk in enumerate(chunks):
            record_id = "::".join(
                [
                    "appendix_clean",
                    str(record.get("law_name") or record.get("law_id") or "unknown"),
                    str(record.get("appendix_key") or record.get("appendix_title") or "unknown"),
                    str(chunk_index),
                ]
            )
            records.append(
                {
                    "id": record_id,
                    "text": chunk,
                    "doc_type": "law_appendix",
                    "section_type": appendix_type,
                    "source_group": "01_current_law_appendix",
                    "law_name": record.get("law_name"),
                    "law_id": record.get("law_id"),
                    "mst": record.get("mst"),
                    "ef_yd": record.get("ef_yd"),
                    "kind_name": record.get("kind_name"),
                    "appendix_key": record.get("appendix_key"),
                    "appendix_no": record.get("appendix_no"),
                    "appendix_kind": record.get("appendix_kind"),
                    "appendix_type": appendix_type,
                    "appendix_title": record.get("appendix_title"),
                    "processing_policy": record.get("processing_policy", {}),
                    "text_source": _resolve_text_source(asset_record),
                    "best_text_reason": asset_record.get("best_text_reason") if asset_record is not None else None,
                    "best_asset_local_path": asset_record.get("best_asset_local_path") if asset_record is not None else None,
                    "normalized_asset_bundle_path": asset_record.get("normalized_asset_bundle_path") if asset_record is not None else None,
                    "chunk_index": chunk_index,
                    "structure_preserved": preserve_structure,
                    "source_file_path": str(path),
                }
            )

    return records


def build_appendix_table_records(
    normalized_appendix_base_dir: str | Path = "data/normalized/01_current_law_appendix",
    max_chars: int = 1200,
    overlap: int = 150,
    *,
    include_types: Sequence[str] = ("table_appendix", "form_appendix"),
    normalized_appendix_asset_base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    return build_appendix_clean_records(
        normalized_appendix_base_dir=normalized_appendix_base_dir,
        max_chars=max_chars,
        overlap=overlap,
        include_types=include_types,
        preserve_structure=True,
        normalized_appendix_asset_base_dir=normalized_appendix_asset_base_dir,
    )


def build_and_write_appendix_datasets(
    normalized_appendix_base_dir: str | Path = "data/normalized/01_current_law_appendix",
    output_dir: str | Path = "data/dataset",
    max_chars: int = 1200,
    overlap: int = 150,
    *,
    normalized_appendix_asset_base_dir: str | Path | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)

    raw_records = build_appendix_raw_records(
        normalized_appendix_base_dir=normalized_appendix_base_dir,
        normalized_appendix_asset_base_dir=normalized_appendix_asset_base_dir,
    )
    clean_records = build_appendix_clean_records(
        normalized_appendix_base_dir=normalized_appendix_base_dir,
        max_chars=max_chars,
        overlap=overlap,
        include_types=("appendix_document",),
        preserve_structure=True,
        normalized_appendix_asset_base_dir=normalized_appendix_asset_base_dir,
    )
    table_records = build_appendix_table_records(
        normalized_appendix_base_dir=normalized_appendix_base_dir,
        max_chars=max_chars,
        overlap=overlap,
        normalized_appendix_asset_base_dir=normalized_appendix_asset_base_dir,
    )

    write_jsonl(raw_records, output_dir / "legal_appendix_raw.jsonl")
    write_jsonl(clean_records, output_dir / "legal_appendix_clean.jsonl")
    write_jsonl(table_records, output_dir / "legal_appendix_table.jsonl")

    appendix_type_counts: dict[str, int] = {}
    for record in raw_records:
        appendix_type = str(record.get("appendix_type") or "unknown")
        appendix_type_counts[appendix_type] = appendix_type_counts.get(appendix_type, 0) + 1

    manifest = {
        "appendix_raw_count": len(raw_records),
        "appendix_clean_count": len(clean_records),
        "appendix_table_count": len(table_records),
        "appendix_type_counts": appendix_type_counts,
        "asset_enriched": normalized_appendix_asset_base_dir is not None,
        "max_chars": max_chars,
        "overlap": overlap,
    }

    _write_json(output_dir / "appendix_dataset_manifest.json", manifest)
    return manifest
