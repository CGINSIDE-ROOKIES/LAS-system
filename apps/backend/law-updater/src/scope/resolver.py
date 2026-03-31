from __future__ import annotations

import re
from typing import Any

from src.collector.law_body_collector import (
    build_law_ref_from_search_item,
    
    get_law_items_from_search,
)
from src.common.law_meta import (
    normalize_classified_level,
    normalize_kind_name,
)

from src.scope.system_diagram_parser import collect_descendant_law_refs


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def classify_law_level(kind_name: str | None) -> str:
    text = str(kind_name or "").strip()

    if "법률" in text or text == "법":
        return "법"
    if "대통령령" in text or "시행령" in text:
        return "시행령"
    if "부령" in text or "시행규칙" in text or "규칙" in text:
        return "시행규칙"

    return text or "기타"


def is_allowed_level(classified_level: str, allowed_levels: set[str]) -> bool:
    if not allowed_levels:
        return True

    if classified_level in allowed_levels:
        return True

    if (
        "직속하위법령" in allowed_levels
        and classified_level in {"시행령", "시행규칙"}
    ):
        return True

    return False


def _dedup_key(ref: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(ref.get("law_id") or ""),
        str(ref.get("mst") or ""),
        _normalize_name(str(ref.get("law_name") or "")),
    )


def _merge_ref(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    return merged


def _index_search_refs(items: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}

    for item in items:
        ref = build_law_ref_from_search_item(item)
        indexed[_dedup_key(ref)] = ref

        law_id = str(ref.get("law_id") or "")
        mst = str(ref.get("mst") or "")
        law_name = _normalize_name(str(ref.get("law_name") or ""))

        if law_id:
            indexed[(law_id, "", "")] = ref
        if mst:
            indexed[("", mst, "")] = ref
        if law_name:
            indexed[("", "", law_name)] = ref

    return indexed


def _select_family_refs_from_system_diagram(
    current_law_list_payload: dict[str, Any],
    root_law_name: str,
    allowed_levels: set[str],
    system_diagram_detail: dict[str, Any],
) -> list[dict[str, Any]]:
    items = get_law_items_from_search(current_law_list_payload)
    search_index = _index_search_refs(items)
    diagram_refs = collect_descendant_law_refs(system_diagram_detail, root_law_name)

    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for diagram_ref in diagram_refs:
        candidates = [
            search_index.get(_dedup_key(diagram_ref)),
            search_index.get((str(diagram_ref.get("law_id") or ""), "", "")),
            search_index.get(("", str(diagram_ref.get("mst") or ""), "")),
            search_index.get(("", "", _normalize_name(str(diagram_ref.get("law_name") or "")))),
        ]

        enriched = dict(diagram_ref)
        for candidate in candidates:
            if isinstance(candidate, dict):
                enriched = _merge_ref(candidate, enriched)
                enriched = _merge_ref(enriched, candidate)
                break

        enriched["kind_name"] = normalize_kind_name(enriched.get("kind_name"))
        classified_level = classify_law_level(enriched.get("kind_name"))
        if not is_allowed_level(classified_level, allowed_levels):
            continue

        enriched["classified_level"] = classified_level
        enriched["scope_source"] = "system_diagram"

        dedup_key = _dedup_key(enriched)
        if dedup_key in seen:
            continue

        seen.add(dedup_key)
        refs.append(enriched)

    return refs


def _select_family_refs_from_name_search(
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
        kind_name = normalize_kind_name(ref.get("kind_name"))

        if normalized_root not in _normalize_name(law_name):
            continue

        classified_level = classify_law_level(kind_name)
        if not is_allowed_level(classified_level, allowed_levels):
            continue

        ref["kind_name"] = kind_name
        ref["classified_level"] = classified_level

        dedup_key = _dedup_key(ref)
        if dedup_key in seen:
            continue

        seen.add(dedup_key)
        refs.append(ref)

    return refs


def select_family_law_refs_from_search(
    current_law_list_payload: dict[str, Any],
    root_law_name: str,
    allowed_levels: set[str],
    *,
    system_diagram_detail: dict[str, Any] | None = None,
    include_descendants_from_system_diagram: bool = False,
) -> list[dict[str, Any]]:
    if include_descendants_from_system_diagram and isinstance(system_diagram_detail, dict):
        exact_refs = _select_family_refs_from_system_diagram(
            current_law_list_payload=current_law_list_payload,
            root_law_name=root_law_name,
            allowed_levels=allowed_levels,
            system_diagram_detail=system_diagram_detail,
        )
        if exact_refs:
            return exact_refs

    return _select_family_refs_from_name_search(
        current_law_list_payload=current_law_list_payload,
        root_law_name=root_law_name,
        allowed_levels=allowed_levels,
    )
