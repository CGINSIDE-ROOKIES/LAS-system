from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.common.io_utils import _safe_filename, _write_json
from src.common.payload_utils import (
    _ensure_success_payload,
    _first_non_empty,
    _walk_objects,
)
from src.core.http_client import execute_json_request
from src.core.request_builder import build_request

def get_output_config(
    scope: dict[str, Any],
    file_id: str = "01_current_law",
) -> dict[str, Any]:
    outputs = scope.get("outputs", [])
    if not isinstance(outputs, list):
        raise ValueError("collection_scope.outputs must be a list")

    for output in outputs:
        if isinstance(output, dict) and output.get("file_id") == file_id:
            return output

    raise KeyError(f"Output config not found for file_id='{file_id}'")


def get_root_law_names(
    scope: dict[str, Any],
    file_id: str = "01_current_law",
) -> list[str]:
    output = get_output_config(scope, file_id=file_id)
    roots = output.get("roots", {})

    if not isinstance(roots, dict):
        raise ValueError("outputs[].roots must be a dict")

    names: list[str] = []
    seen: set[str] = set()

    for group_names in roots.values():
        if not isinstance(group_names, list):
            continue

        for name in group_names:
            normalized = str(name).strip()
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            names.append(normalized)

    return names


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


def _is_generic_error_payload(payload: dict[str, Any]) -> bool:
    keys = set(payload.keys())
    return keys.issubset({"result", "msg"}) and "msg" in payload


def _ensure_success_payload(endpoint_key: str, payload: dict[str, Any]) -> None:
    if _is_generic_error_payload(payload):
        raise RuntimeError(
            f"{endpoint_key} returned error payload: {payload}"
        )


def _walk_objects(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_objects(item)


def _first_non_empty(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", []):
            return value
    return None


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def extract_system_diagram_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for obj in _walk_objects(payload):
        if not isinstance(obj, dict):
            continue

        law_id = _first_non_empty(
            obj,
            "법령ID",
            "lawId",
            "law_id",
            "ID",
            "id",
        )
        mst = _first_non_empty(
            obj,
            "법령일련번호",
            "법령 일련번호",
            "lawSerialNo",
            "law_serial_no",
            "MST",
            "mst",
        )
        law_name = _first_non_empty(
            obj,
            "법령명",
            "법령명한글",
            "법령",
            "lawName",
            "law_name",
            "law_name_ko",
        )

        if law_id is None and mst is None:
            continue

        ref = {
            "law_id": str(law_id) if law_id is not None else None,
            "mst": str(mst) if mst is not None else None,
            "law_name": str(law_name) if law_name is not None else None,
        }

        dedup_key = (
            ref["law_id"] or "",
            ref["mst"] or "",
            ref["law_name"] or "",
        )
        if dedup_key in seen:
            continue

        seen.add(dedup_key)
        refs.append(ref)

    return refs


def select_best_system_diagram_ref(
    refs: list[dict[str, Any]],
    query: str,
) -> dict[str, Any] | None:
    if not refs:
        return None

    normalized_query = _normalize_name(query)

    exact = [
        ref
        for ref in refs
        if _normalize_name(ref.get("law_name") or "") == normalized_query
    ]
    if exact:
        return exact[0]

    partial = [
        ref
        for ref in refs
        if normalized_query in _normalize_name(ref.get("law_name") or "")
    ]
    if partial:
        return partial[0]

    return refs[0]


def fetch_current_law_list(
    registry: dict[str, Any],
    oc: str,
    query: str,
) -> dict[str, Any]:
    request = build_request(
        registry,
        "law_current_list",
        {
            "OC": oc,
            "query": query,
            "nw": "3",
        },
    )
    payload = execute_json_request(request)
    _ensure_success_payload("law_current_list", payload)
    return payload


def fetch_system_diagram_list(
    registry: dict[str, Any],
    oc: str,
    query: str,
) -> dict[str, Any]:
    request = build_request(
        registry,
        "law_system_diagram_list",
        {
            "OC": oc,
            "query": query,
        },
    )
    payload = execute_json_request(request)
    _ensure_success_payload("law_system_diagram_list", payload)
    return payload


def fetch_system_diagram_detail(
    registry: dict[str, Any],
    oc: str,
    ref: dict[str, Any],
) -> dict[str, Any]:
    runtime_params: dict[str, Any] = {"OC": oc}

    if ref.get("law_id"):
        runtime_params["ID"] = ref["law_id"]
    elif ref.get("mst"):
        runtime_params["MST"] = ref["mst"]
    else:
        raise ValueError("system diagram detail requires law_id or mst")

    request = build_request(
        registry,
        "law_system_diagram_detail",
        runtime_params,
    )
    payload = execute_json_request(request)
    _ensure_success_payload("law_system_diagram_detail", payload)
    return payload


def collect_root_law_raw(
    registry: dict[str, Any],
    oc: str,
    law_name: str,
    save_dir: str | Path | None = None,
) -> dict[str, Any]:
    current_law_list = fetch_current_law_list(registry, oc, law_name)
    system_diagram_list = fetch_system_diagram_list(registry, oc, law_name)

    refs = extract_system_diagram_refs(system_diagram_list)
    best_ref = select_best_system_diagram_ref(refs, law_name)

    system_diagram_detail: dict[str, Any] | None = None
    if best_ref is not None:
        system_diagram_detail = fetch_system_diagram_detail(
            registry,
            oc,
            best_ref,
        )

    record = {
        "law_name": law_name,
        "current_law_list": current_law_list,
        "system_diagram_list": system_diagram_list,
        "system_diagram_ref": best_ref,
        "system_diagram_detail": system_diagram_detail,
    }

    if save_dir is not None:
        base_dir = Path(save_dir)
        stem = _safe_filename(law_name)

        _write_json(
            base_dir / f"{stem}__law_current_list.json",
            current_law_list,
        )
        _write_json(
            base_dir / f"{stem}__law_system_diagram_list.json",
            system_diagram_list,
        )
        if system_diagram_detail is not None:
            _write_json(
                base_dir / f"{stem}__law_system_diagram_detail.json",
                system_diagram_detail,
            )
        _write_json(
            base_dir / f"{stem}__raw_bundle.json",
            record,
        )

    return record


def collect_all_root_laws(
    scope: dict[str, Any],
    registry: dict[str, Any],
    oc: str,
    save_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for law_name in get_root_law_names(scope):
        record = collect_root_law_raw(
            registry=registry,
            oc=oc,
            law_name=law_name,
            save_dir=save_dir,
        )
        results.append(record)

    return results