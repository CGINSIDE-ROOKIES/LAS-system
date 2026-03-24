from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from src.common.appendix_scope import is_target_appendix
from src.common.io_utils import _read_json, write_jsonl
from src.common.law_meta import build_law_uid, normalize_kind_name, normalize_classified_level


ARTICLE_REF_PATTERN = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
WHITESPACE_PATTERN = re.compile(r"\s+")


def _normalize_space(text: Any) -> str:
    if text in (None, ""):
        return ""
    return WHITESPACE_PATTERN.sub(" ", str(text)).strip()


def _normalize_structure(text: Any) -> str:
    if text in (None, ""):
        return ""

    normalized_lines: list[str] = []
    previous_blank = False
    for raw_line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
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


def _normalize_numeric_token(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    stripped = digits.lstrip("0")
    return stripped or "0"


def extract_article_keys(text: Any) -> list[str]:
    normalized = _normalize_space(text)
    if not normalized:
        return []

    keys: list[str] = []
    seen: set[str] = set()
    for match in ARTICLE_REF_PATTERN.finditer(normalized):
        main_no = _normalize_numeric_token(match.group(1))
        branch_no = _normalize_numeric_token(match.group(2))
        if main_no is None:
            continue
        key = main_no if branch_no is None else f"{main_no}-{branch_no}"
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _normalize_appendix_no(value: Any) -> str | None:
    token = _normalize_numeric_token(value)
    if token is None:
        return None
    return token


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


def _dedup_sections(sections: Iterable[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for section in sections:
        normalized = _normalize_structure(section)
        if not normalized:
            continue
        key = _normalize_space(normalized)
        if key in seen:
            continue
        seen.add(key)
        results.append(normalized)

    return results


def _load_appendix_asset_index(
    normalized_appendix_asset_base_dir: str | Path | None,
) -> dict[str, dict[str, Any]]:
    if normalized_appendix_asset_base_dir is None:
        return {}

    base_dir = Path(normalized_appendix_asset_base_dir)
    if not base_dir.exists():
        return {}

    index: dict[str, dict[str, Any]] = {}
    for path in sorted(base_dir.rglob("*__appendix_assets.parsed.json")):
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
            indexed = dict(record)
            indexed["normalized_asset_bundle_path"] = str(path)
            index[str(appendix_id)] = indexed
    return index


def _select_appendix_bundle_text(record: dict[str, Any], *, asset_record: dict[str, Any] | None = None) -> str:
    candidate_values: list[Any] = []

    if asset_record is not None and str(asset_record.get("best_text_source") or "").strip() not in {"", "none"}:
        candidate_values.extend(
            [
                asset_record.get("best_text_raw"),
                asset_record.get("best_text"),
            ]
        )

    candidate_values.extend(
        [
            record.get("api_document_markdown"),
            record.get("api_narrative_markdown"),
            record.get("api_table_markdown_text"),
            record.get("api_text_raw"),
            record.get("api_text"),
        ]
    )

    for value in candidate_values:
        if value in (None, ""):
            continue
        return _normalize_structure(value)
    return ""


def _build_appendix_bundle_text(record: dict[str, Any], *, asset_record: dict[str, Any] | None = None) -> str:
    appendix_title = _normalize_space(record.get("appendix_title") or record.get("appendix_title_raw") or "별표") or "별표"
    appendix_no = _normalize_appendix_no(record.get("appendix_no"))
    appendix_kind = _normalize_space(record.get("appendix_kind") or "별표")
    kind_name = normalize_kind_name(record.get("kind_name"))
    law_level = normalize_classified_level(kind_name, record.get("classified_level"))
    reference_article_keys = extract_article_keys(record.get("appendix_title_raw") or record.get("appendix_title"))

    lines: list[str] = []
    if record.get("law_name"):
        lines.append(f"법령명: {record['law_name']}")
    if kind_name:
        lines.append(f"법령종류: {kind_name}")
    if law_level:
        lines.append(f"법령레벨: {law_level}")
    lines.append(f"구성요소: {record.get('appendix_type') or 'appendix_document'}")
    if appendix_kind:
        lines.append(f"별표구분: {appendix_kind}")
    if appendix_no:
        lines.append(f"별표번호: {appendix_no}")
    lines.append(_render_prefixed_text("별표제목:", appendix_title))
    if reference_article_keys:
        lines.append(
            "관련조문: " + ", ".join(
                f"제{key.replace('-', '조의')}조" if "-" not in key else f"제{key.split('-')[0]}조의{key.split('-')[1]}"
                for key in reference_article_keys
            )
        )

    best_text = _select_appendix_bundle_text(record, asset_record=asset_record)
    bundle_text = "\n".join(line for line in lines if line).strip()
    if best_text:
        bundle_text = f"{bundle_text}\n{best_text}".strip()

    return _normalize_structure(bundle_text)


def _build_appendix_preview(text: str, *, max_chars: int = 600) -> str:
    normalized = _normalize_structure(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _appendix_marker_texts(record: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    appendix_no = _normalize_appendix_no(record.get("appendix_no"))
    if appendix_no is not None:
        markers.append(f"별표 {appendix_no}")
        markers.append(f"별표{appendix_no}")
    appendix_title_raw = _normalize_space(record.get("appendix_title_raw"))
    appendix_title = _normalize_space(record.get("appendix_title"))
    if appendix_title_raw:
        markers.append(appendix_title_raw)
    if appendix_title and appendix_title not in markers:
        markers.append(appendix_title)
    return markers


def _iter_article_units(normalized_base_dir: str | Path) -> Iterable[tuple[str, Path, dict[str, Any], dict[str, Any]]]:
    base_dir = Path(normalized_base_dir)
    for path in sorted(base_dir.rglob("*__parsed_law.json")):
        payload = _read_json(path)
        law_uid = build_law_uid(payload.get("law_id"), payload.get("mst"), payload.get("law_name"))
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            continue
        for article in articles:
            if not isinstance(article, dict):
                continue
            article_key = _normalize_space(article.get("article_key") or article.get("article_no_display") or article.get("article_no"))
            if not article_key:
                continue
            yield law_uid, path, payload, article


def _build_article_index(normalized_base_dir: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for law_uid, path, payload, article in _iter_article_units(normalized_base_dir):
        article_key = _normalize_space(article.get("article_key") or article.get("article_no_display") or article.get("article_no"))
        index[(law_uid, article_key)] = {
            "law_uid": law_uid,
            "law_name": payload.get("law_name"),
            "law_id": payload.get("law_id"),
            "mst": payload.get("mst"),
            "article_key": article_key,
            "article_no": article.get("article_no"),
            "article_no_display": article.get("article_no_display") or article.get("article_no"),
            "article_title": article.get("article_title") or article.get("article_title_raw"),
            "article_text": article.get("article_text_raw") or article.get("article_text") or "",
            "source_file_path": str(path),
        }
    return index


def build_article_appendix_links(
    *,
    normalized_base_dir: str | Path,
    normalized_appendix_base_dir: str | Path,
    normalized_appendix_asset_base_dir: str | Path | None = None,
) -> dict[str, Any]:
    article_index = _build_article_index(normalized_base_dir)
    asset_index = _load_appendix_asset_index(normalized_appendix_asset_base_dir)

    article_links: dict[tuple[str, str], list[dict[str, Any]]] = {}
    link_records: list[dict[str, Any]] = []
    appendix_bundle_records: list[dict[str, Any]] = []
    unresolved_appendix_records: list[dict[str, Any]] = []
    seen_link_ids: set[str] = set()

    appendix_base_dir = Path(normalized_appendix_base_dir)
    for path in sorted(appendix_base_dir.rglob("*__parsed_appendix.json")):
        bundle = _read_json(path)
        law_uid = build_law_uid(bundle.get("law_id"), bundle.get("mst"), bundle.get("law_name"))
        appendix_records = bundle.get("appendix_records", [])
        if not isinstance(appendix_records, list):
            continue

        same_law_articles = {
            article_key: article_meta
            for (candidate_law_uid, article_key), article_meta in article_index.items()
            if candidate_law_uid == law_uid
        }

        for record in appendix_records:
            if not isinstance(record, dict):
                continue
            if not is_target_appendix(record.get("appendix_kind"), record.get("appendix_title"), record.get("appendix_key")):
                continue

            appendix_id = str(record.get("id") or f"appendix::{law_uid}::{record.get('appendix_key') or record.get('appendix_title') or 'unknown'}")
            appendix_key = _normalize_space(record.get("appendix_key") or record.get("appendix_title") or appendix_id)
            appendix_title = _normalize_space(record.get("appendix_title") or record.get("appendix_title_raw") or "별표") or "별표"
            appendix_no = _normalize_appendix_no(record.get("appendix_no"))
            title_reference_article_keys = extract_article_keys(record.get("appendix_title_raw") or record.get("appendix_title"))
            marker_texts = _appendix_marker_texts(record)
            asset_record = asset_index.get(appendix_id)
            bundle_text = _build_appendix_bundle_text(record, asset_record=asset_record)
            bundle_preview = _build_appendix_preview(bundle_text)

            reverse_article_keys: list[str] = []
            seen_reverse_keys: set[str] = set()
            for article_key, article_meta in same_law_articles.items():
                haystack = _normalize_space(
                    " ".join(
                        [
                            str(article_meta.get("article_no_display") or ""),
                            str(article_meta.get("article_title") or ""),
                            str(article_meta.get("article_text") or ""),
                        ]
                    )
                )
                if not haystack:
                    continue
                if any(marker and marker in haystack for marker in marker_texts):
                    if article_key not in seen_reverse_keys:
                        seen_reverse_keys.add(article_key)
                        reverse_article_keys.append(article_key)

            if title_reference_article_keys:
                matched_article_keys = [key for key in title_reference_article_keys if (law_uid, key) in article_index]
                if not matched_article_keys:
                    matched_article_keys = title_reference_article_keys
                match_types = ["appendix_title_reference"]
                if reverse_article_keys:
                    match_types.append("law_body_reverse_match")
            else:
                matched_article_keys = reverse_article_keys
                match_types = ["law_body_reverse_match"] if reverse_article_keys else []

            appendix_bundle_record = {
                "appendix_id": appendix_id,
                "law_uid": law_uid,
                "law_name": bundle.get("law_name") or record.get("law_name"),
                "law_id": bundle.get("law_id") or record.get("law_id"),
                "appendix_key": appendix_key,
                "appendix_no": appendix_no,
                "appendix_kind": record.get("appendix_kind"),
                "appendix_type": record.get("appendix_type"),
                "appendix_title": appendix_title,
                "appendix_title_raw": record.get("appendix_title_raw"),
                "title_reference_article_keys": title_reference_article_keys,
                "reverse_article_keys": reverse_article_keys,
                "matched_article_keys": matched_article_keys,
                "match_types": match_types,
                "bundle_text": bundle_text,
                "bundle_preview": bundle_preview,
                "table_count": int(record.get("api_table_count") or 0),
                "source_file_path": str(path),
                "asset_bundle_path": asset_record.get("normalized_asset_bundle_path") if asset_record else None,
            }
            appendix_bundle_records.append(appendix_bundle_record)

            if not matched_article_keys:
                unresolved_appendix_records.append(dict(appendix_bundle_record))
                continue

            for article_key in matched_article_keys:
                article_meta = article_index.get((law_uid, article_key))
                if article_meta is None:
                    unresolved_appendix_records.append(dict(appendix_bundle_record))
                    continue

                link_id = "::".join(["article_appendix", law_uid, article_key, appendix_key])
                if link_id in seen_link_ids:
                    continue
                seen_link_ids.add(link_id)

                item = {
                    "appendix_id": appendix_id,
                    "appendix_key": appendix_key,
                    "appendix_no": appendix_no,
                    "appendix_title": appendix_title,
                    "appendix_title_raw": record.get("appendix_title_raw"),
                    "appendix_kind": record.get("appendix_kind"),
                    "appendix_type": record.get("appendix_type"),
                    "match_types": match_types,
                    "bundle_text": bundle_text,
                    "bundle_preview": bundle_preview,
                    "table_count": int(record.get("api_table_count") or 0),
                    "source_file_path": str(path),
                    "asset_bundle_path": asset_record.get("normalized_asset_bundle_path") if asset_record else None,
                }
                article_links.setdefault((law_uid, article_key), []).append(item)

                link_records.append(
                    {
                        "id": link_id,
                        "law_uid": law_uid,
                        "law_name": article_meta.get("law_name"),
                        "law_id": article_meta.get("law_id"),
                        "article_key": article_key,
                        "article_no": article_meta.get("article_no"),
                        "article_no_display": article_meta.get("article_no_display"),
                        "appendix_id": appendix_id,
                        "appendix_key": appendix_key,
                        "appendix_no": appendix_no,
                        "appendix_title": appendix_title,
                        "match_types": match_types,
                        "bundle_preview": bundle_preview,
                        "source_file_path": str(path),
                    }
                )

    for items in article_links.values():
        items.sort(key=lambda item: (item.get("appendix_key") or "", item.get("appendix_id") or ""))

    article_with_appendix_count = len(article_links)
    total_appendix_count = len(appendix_bundle_records)
    linked_appendix_ids = {record["appendix_id"] for record in link_records}
    unresolved_appendix_count = len({record["appendix_id"] for record in unresolved_appendix_records})

    manifest = {
        "appendix_bundle_count": total_appendix_count,
        "article_with_appendix_count": article_with_appendix_count,
        "article_appendix_link_count": len(link_records),
        "linked_appendix_count": len(linked_appendix_ids),
        "unresolved_appendix_count": unresolved_appendix_count,
    }

    return {
        "article_links": article_links,
        "link_records": link_records,
        "appendix_bundle_records": appendix_bundle_records,
        "unresolved_appendix_records": unresolved_appendix_records,
        "manifest": manifest,
    }


def augment_law_records_with_appendices(
    law_records: list[dict[str, Any]],
    *,
    article_links: dict[tuple[str, str], list[dict[str, Any]]],
    include_bundle_text_in_payload: bool = True,
) -> list[dict[str, Any]]:
    augmented: list[dict[str, Any]] = []

    for row in law_records:
        updated = dict(row)
        law_uid = build_law_uid(row.get("law_id"), row.get("mst"), row.get("law_name"))
        article_key = _normalize_space(row.get("article_key"))

        items = []
        if row.get("doc_type") == "law" and row.get("section_type") == "article" and article_key:
            items = [dict(item) for item in article_links.get((law_uid, article_key), [])]

        appendix_vector_sections: list[str] = []
        related_appendices: list[dict[str, Any]] = []
        for item in items:
            appendix_vector_sections.append(item.get("bundle_text") or item.get("bundle_preview") or item.get("appendix_title") or "")
            appendix_payload_item = {
                "appendix_id": item.get("appendix_id"),
                "appendix_key": item.get("appendix_key"),
                "appendix_no": item.get("appendix_no"),
                "appendix_title": item.get("appendix_title"),
                "appendix_kind": item.get("appendix_kind"),
                "appendix_type": item.get("appendix_type"),
                "match_types": item.get("match_types") or [],
                "bundle_preview": item.get("bundle_preview"),
                "table_count": item.get("table_count"),
                "source_file_path": item.get("source_file_path"),
                "asset_bundle_path": item.get("asset_bundle_path"),
            }
            if include_bundle_text_in_payload:
                appendix_payload_item["bundle_text"] = item.get("bundle_text")
            related_appendices.append(appendix_payload_item)

        appendix_vector_text = _normalize_structure("\n\n".join(section for section in appendix_vector_sections if section).strip())
        if not appendix_vector_text:
            appendix_vector_text = "[NO_APPENDIX_LINKED]"

        updated["has_related_appendix"] = bool(items)
        updated["related_appendix_count"] = len(items)
        updated["related_appendix_ids"] = [item.get("appendix_id") for item in items]
        updated["related_appendix_keys"] = [item.get("appendix_key") for item in items]
        updated["related_appendix_nos"] = [item.get("appendix_no") for item in items]
        updated["related_appendix_titles"] = [item.get("appendix_title") for item in items]
        updated["related_appendix_match_types"] = [item.get("match_types") or [] for item in items]
        updated["related_appendix_previews"] = [item.get("bundle_preview") for item in items]
        updated["related_appendices"] = related_appendices
        updated["appendix_vector_text"] = appendix_vector_text
        updated["body_vector_text"] = _normalize_structure(updated.get("text") or "")

        augmented.append(updated)

    return augmented


def write_article_appendix_outputs(
    output_dir: str | Path,
    *,
    link_records: list[dict[str, Any]],
    appendix_bundle_records: list[dict[str, Any]],
    unresolved_appendix_records: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    write_jsonl(link_records, output_path / "article_appendix_links.jsonl")
    write_jsonl(appendix_bundle_records, output_path / "appendix_bundle_records.jsonl")
    write_jsonl(unresolved_appendix_records, output_path / "unresolved_appendix_records.jsonl")
    with (output_path / "article_appendix_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
