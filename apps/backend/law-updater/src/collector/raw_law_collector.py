from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.common.io_utils import _safe_filename, _write_json
from src.common.payload_utils import (
    _ensure_success_payload,
    _first_non_empty,
    _walk_objects,
)
from src.core.http_client import execute_api_request
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
    result = execute_api_request(request)
    payload = result["parsed"]

    if not isinstance(payload, dict):
        raise RuntimeError("law_current_list parsed payload must be dict")

    _ensure_success_payload("law_current_list", payload)
    return {
        "response_meta": {
            "format": result["format"],
            "content_type": result["content_type"],
            "status_code": result["status_code"],
            "url": result["url"],
        },
        "raw_text": result["text"],
        "parsed": payload,
    }


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
    result = execute_api_request(request)
    payload = result["parsed"]

    if not isinstance(payload, dict):
        raise RuntimeError("law_system_diagram_list parsed payload must be dict")

    _ensure_success_payload("law_system_diagram_list", payload)
    return {
        "response_meta": {
            "format": result["format"],
            "content_type": result["content_type"],
            "status_code": result["status_code"],
            "url": result["url"],
        },
        "raw_text": result["text"],
        "parsed": payload,
    }


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
    result = execute_api_request(request)
    payload = result["parsed"]

    if not isinstance(payload, dict):
        raise RuntimeError("law_system_diagram_detail parsed payload must be dict")

    _ensure_success_payload("law_system_diagram_detail", payload)
    return {
        "response_meta": {
            "format": result["format"],
            "content_type": result["content_type"],
            "status_code": result["status_code"],
            "url": result["url"],
        },
        "raw_text": result["text"],
        "parsed": payload,
    }


def collect_root_law_raw(
    registry: dict[str, Any],
    oc: str,
    law_name: str,
    save_dir: str | Path | None = None,
) -> dict[str, Any]:
    current_law_list_result = fetch_current_law_list(registry, oc, law_name)
    system_diagram_list_result = fetch_system_diagram_list(registry, oc, law_name)

    current_law_list = current_law_list_result["parsed"]
    system_diagram_list = system_diagram_list_result["parsed"]

    refs = extract_system_diagram_refs(system_diagram_list)
    best_ref = select_best_system_diagram_ref(refs, law_name)

    system_diagram_detail_result: dict[str, Any] | None = None
    system_diagram_detail: dict[str, Any] | None = None

    if best_ref is not None:
        system_diagram_detail_result = fetch_system_diagram_detail(
            registry,
            oc,
            best_ref,
        )
        system_diagram_detail = system_diagram_detail_result["parsed"]

    record = {
        "law_name": law_name,
        "law_ref": best_ref,
        "current_law_list": current_law_list,
        "current_law_list_response": current_law_list_result,
        "system_diagram_list": system_diagram_list,
        "system_diagram_list_response": system_diagram_list_result,
        "system_diagram_detail": system_diagram_detail,
        "system_diagram_detail_response": system_diagram_detail_result,
    }

    if save_dir is not None:
        base_dir = Path(save_dir)
        stem = _safe_filename(law_name)

        _write_json(
            base_dir / f"{stem}__law_current_list.parsed.json",
            current_law_list,
        )
        _write_json(
            base_dir / f"{stem}__law_current_list.response.json",
            current_law_list_result,
        )

        _write_json(
            base_dir / f"{stem}__law_system_diagram_list.parsed.json",
            system_diagram_list,
        )
        _write_json(
            base_dir / f"{stem}__law_system_diagram_list.response.json",
            system_diagram_list_result,
        )

        if system_diagram_detail is not None:
            _write_json(
                base_dir / f"{stem}__law_system_diagram_detail.parsed.json",
                system_diagram_detail,
            )

        if system_diagram_detail_result is not None:
            _write_json(
                base_dir / f"{stem}__law_system_diagram_detail.response.json",
                system_diagram_detail_result,
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