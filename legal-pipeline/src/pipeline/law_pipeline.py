from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.collector.law_body_collector import (
    build_law_ref_from_search_item,
    fetch_law_body_by_ref,
    get_law_items_from_search,
)
from src.collector.law_sub_article_collector import (
    SubArticleMode,
    collect_sub_articles_for_parsed_law,
)
from src.collector.raw_law_collector import (
    collect_root_law_raw,
    get_output_config,
    get_root_law_names,
)
from src.parser.law_parser import parse_law_body, save_parsed_law


def _safe_filename(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^\w가-힣.-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "unnamed"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def classify_law_level(kind_name: str | None) -> str:
    text = str(kind_name or "").strip()

    if "법률" in text or text == "법":
        return "법"
    if "대통령령" in text or "시행령" in text:
        return "시행령"
    if "부령" in text or "시행규칙" in text:
        return "시행규칙"

    return text or "기타"


def get_allowed_law_levels(
    scope: dict[str, Any],
    file_id: str = "01_current_law",
) -> set[str]:
    output = get_output_config(scope, file_id=file_id)
    include_law_levels = output.get("include_law_levels", [])

    if not isinstance(include_law_levels, list):
        raise ValueError("include_law_levels must be a list")

    return {str(level).strip() for level in include_law_levels if str(level).strip()}


def is_allowed_level(classified_level: str, allowed_levels: set[str]) -> bool:
    if classified_level in allowed_levels:
        return True

    if (
        "직속하위법령" in allowed_levels
        and classified_level in {"시행령", "시행규칙"}
    ):
        return True

    return False


def select_family_law_refs_from_search(
    current_law_list_payload: dict[str, Any],
    root_law_name: str,
    allowed_levels: set[str],
) -> list[dict[str, Any]]:
    items = get_law_items_from_search(current_law_list_payload)

    normalized_root = _normalize_name(root_law_name)
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for item in items:
        ref = build_law_ref_from_search_item(item)
        law_name = str(ref.get("law_name") or "")
        kind_name = str(ref.get("kind_name") or "")

        if normalized_root not in _normalize_name(law_name):
            continue

        classified_level = classify_law_level(kind_name)
        if not is_allowed_level(classified_level, allowed_levels):
            continue

        ref["classified_level"] = classified_level

        dedup_key = (
            str(ref.get("law_id") or ""),
            str(ref.get("mst") or ""),
            str(ref.get("ef_yd") or ""),
        )
        if dedup_key in seen:
            continue

        seen.add(dedup_key)
        refs.append(ref)

    return refs


def _save_law_body_payload(
    law_ref: dict[str, Any],
    law_body: dict[str, Any],
    save_dir: Path,
) -> Path:
    stem = _safe_filename(str(law_ref.get("law_name") or "unnamed"))
    output_path = save_dir / f"{stem}__law_current_detail.json"
    _write_json(output_path, law_body)
    return output_path


def collect_root_law_family(
    scope: dict[str, Any],
    registry: dict[str, Any],
    oc: str,
    root_law_name: str,
    base_dir: str | Path = "data",
    sub_article_mode: SubArticleMode = "none",
) -> dict[str, Any]:
    base_dir = Path(base_dir)
    root_stem = _safe_filename(root_law_name)

    raw_root_dir = base_dir / "raw" / "01_current_law" / root_stem
    raw_body_dir = base_dir / "raw" / "01_current_law_body" / root_stem
    raw_sub_dir = base_dir / "raw" / "01_current_sub_article" / root_stem
    normalized_dir = base_dir / "normalized" / "01_current_law" / root_stem
    manifest_dir = base_dir / "manifest" / "01_current_law" / root_stem

    raw_record = collect_root_law_raw(
        registry=registry,
        oc=oc,
        law_name=root_law_name,
        save_dir=raw_root_dir,
    )

    allowed_levels = get_allowed_law_levels(scope)
    family_refs = select_family_law_refs_from_search(
        raw_record["current_law_list"],
        root_law_name=root_law_name,
        allowed_levels=allowed_levels,
    )

    collected_laws: list[dict[str, Any]] = []

    for law_ref in family_refs:
        law_body = fetch_law_body_by_ref(registry, oc, law_ref)
        raw_body_path = _save_law_body_payload(law_ref, law_body, raw_body_dir)

        parsed_law = parse_law_body(law_body, law_ref=law_ref)
        parsed_path = save_parsed_law(parsed_law, normalized_dir)

        sub_records = collect_sub_articles_for_parsed_law(
            registry=registry,
            oc=oc,
            law_ref=law_ref,
            parsed_law=parsed_law,
            mode=sub_article_mode,
            save_dir=raw_sub_dir / _safe_filename(str(law_ref.get("law_name") or "unnamed")),
        )

        collected_laws.append(
            {
                "law_name": law_ref.get("law_name"),
                "law_id": law_ref.get("law_id"),
                "mst": law_ref.get("mst"),
                "ef_yd": law_ref.get("ef_yd"),
                "classified_level": law_ref.get("classified_level"),
                "parsed_articles_count": parsed_law.get("articles_count"),
                "raw_body_path": str(raw_body_path),
                "parsed_path": str(parsed_path),
                "sub_article_count": len(sub_records),
            }
        )

    result = {
        "root_law_name": root_law_name,
        "family_count": len(collected_laws),
        "laws": collected_laws,
        "system_diagram_ref": raw_record.get("system_diagram_ref"),
    }

    _write_json(
        manifest_dir / f"{root_stem}__family_bundle.json",
        result,
    )

    return result


def collect_all_root_law_families(
    scope: dict[str, Any],
    registry: dict[str, Any],
    oc: str,
    base_dir: str | Path = "data",
    max_roots: int | None = None,
    sub_article_mode: SubArticleMode = "none",
) -> list[dict[str, Any]]:
    root_law_names = get_root_law_names(scope)
    if max_roots is not None:
        root_law_names = root_law_names[:max_roots]

    results: list[dict[str, Any]] = []

    for root_law_name in root_law_names:
        result = collect_root_law_family(
            scope=scope,
            registry=registry,
            oc=oc,
            root_law_name=root_law_name,
            base_dir=base_dir,
            sub_article_mode=sub_article_mode,
        )
        results.append(result)

    return results