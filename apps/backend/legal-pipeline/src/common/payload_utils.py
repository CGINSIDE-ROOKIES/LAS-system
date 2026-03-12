from __future__ import annotations

from typing import Any, Iterable


def _first_non_empty(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", []):
            return value
    return None


def _walk_objects(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_objects(item)


def _is_generic_error_payload(payload: dict[str, Any]) -> bool:
    keys = set(payload.keys())
    return keys.issubset({"result", "msg"}) and "msg" in payload


def _ensure_success_payload(endpoint_key: str, payload: dict[str, Any]) -> None:
    if _is_generic_error_payload(payload):
        raise RuntimeError(
            f"{endpoint_key} returned error payload: {payload}"
        )