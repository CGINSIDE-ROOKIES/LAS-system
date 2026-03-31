from __future__ import annotations

import re
from typing import Any

from src.common.payload_utils import _first_non_empty

LAW_ID_KEYS = (
    "법령ID",
    "lawId",
    "law_id",
    "ID",
    "id",
)
MST_KEYS = (
    "법령일련번호",
    "법령 일련번호",
    "lawSerialNo",
    "law_serial_no",
    "MST",
    "mst",
)
LAW_NAME_KEYS = (
    "법령명",
    "법령명한글",
    "법령",
    "lawName",
    "law_name",
    "law_name_ko",
)
KIND_NAME_KEYS = (
    "법령구분명",
    "법종구분명",
    "법종구분",
    "kind_name",
    "law_type_name",
)


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _dedup_key(ref: dict[str, Any]) -> str:
    return "|".join(
        [
            str(ref.get("law_id") or ""),
            str(ref.get("mst") or ""),
            _normalize_name(str(ref.get("law_name") or "")),
        ]
    )


def _is_law_node(obj: dict[str, Any]) -> bool:
    law_id = _first_non_empty(obj, *LAW_ID_KEYS)
    mst = _first_non_empty(obj, *MST_KEYS)
    law_name = _first_non_empty(obj, *LAW_NAME_KEYS)

    if law_id not in (None, "") or mst not in (None, ""):
        return True

    if law_name not in (None, ""):
        text = str(law_name)
        return any(token in text for token in ("법", "령", "규칙", "규정", "조례", "고시"))

    return False


def _build_law_ref(obj: dict[str, Any]) -> dict[str, Any] | None:
    if not _is_law_node(obj):
        return None

    law_id = _first_non_empty(obj, *LAW_ID_KEYS)
    mst = _first_non_empty(obj, *MST_KEYS)
    law_name = _first_non_empty(obj, *LAW_NAME_KEYS)
    kind_name = _first_non_empty(obj, *KIND_NAME_KEYS)

    if law_id in (None, "") and mst in (None, "") and law_name in (None, ""):
        return None

    return {
        "law_id": str(law_id) if law_id not in (None, "") else None,
        "mst": str(mst) if mst not in (None, "") else None,
        "law_name": str(law_name) if law_name not in (None, "") else None,
        "kind_name": str(kind_name) if kind_name not in (None, "") else None,
    }


def _merge_ref(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if merged.get(key) in (None, "") and value not in (None, ""):
            merged[key] = value
    return merged


def parse_system_diagram_tree(payload: dict[str, Any]) -> dict[str, Any]:
    refs_by_key: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str]] = set()

    def walk(node: Any, parent_key: str | None = None) -> None:
        active_parent = parent_key

        if isinstance(node, dict):
            ref = _build_law_ref(node)
            if ref is not None:
                node_key = _dedup_key(ref)
                existing = refs_by_key.get(node_key)
                refs_by_key[node_key] = _merge_ref(existing or {}, ref)

                if parent_key is not None and parent_key != node_key:
                    edges.add((parent_key, node_key))

                active_parent = node_key

            for value in node.values():
                walk(value, active_parent)
            return

        if isinstance(node, list):
            for item in node:
                walk(item, active_parent)

    walk(payload)

    edge_records = [
        {
            "parent": refs_by_key[parent_key],
            "child": refs_by_key[child_key],
        }
        for parent_key, child_key in sorted(edges)
        if parent_key in refs_by_key and child_key in refs_by_key
    ]

    return {
        "nodes": list(refs_by_key.values()),
        "edges": edge_records,
    }


def select_root_law_ref(
    nodes: list[dict[str, Any]],
    root_law_name: str,
) -> dict[str, Any] | None:
    if not nodes:
        return None

    normalized_root = _normalize_name(root_law_name)

    exact = [
        node
        for node in nodes
        if _normalize_name(str(node.get("law_name") or "")) == normalized_root
    ]
    if exact:
        return exact[0]

    partial = [
        node
        for node in nodes
        if normalized_root in _normalize_name(str(node.get("law_name") or ""))
    ]
    if partial:
        return partial[0]

    return nodes[0]


def collect_descendant_law_refs(
    payload: dict[str, Any] | None,
    root_law_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    parsed = parse_system_diagram_tree(payload)
    nodes = parsed["nodes"]
    edges = parsed["edges"]

    root_ref = select_root_law_ref(nodes, root_law_name)
    if root_ref is None:
        return []

    root_key = _dedup_key(root_ref)
    node_map = {_dedup_key(node): node for node in nodes}
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        parent_key = _dedup_key(edge["parent"])
        child_key = _dedup_key(edge["child"])
        adjacency.setdefault(parent_key, set()).add(child_key)

    discovered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append_ref(ref: dict[str, Any]) -> None:
        key = _dedup_key(ref)
        if key in seen:
            return
        seen.add(key)
        discovered.append(ref)

    append_ref(root_ref)

    if root_key in adjacency:
        queue = list(adjacency[root_key])
        while queue:
            key = queue.pop(0)
            ref = node_map.get(key)
            if ref is None or key in seen:
                continue
            append_ref(ref)
            queue.extend(sorted(adjacency.get(key, set())))
        return discovered

    for node in nodes:
        append_ref(node)

    return discovered
