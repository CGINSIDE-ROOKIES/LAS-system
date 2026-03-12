from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.collector.raw_law_collector import fetch_current_law_list
from src.common.io_utils import _safe_filename, _write_json
from src.common.payload_utils import _ensure_success_payload
from src.core.http_client import execute_json_request
from src.core.request_builder import build_request

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


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def get_law_items_from_search(payload: dict[str, Any]) -> list[dict[str, Any]]:
    law_search = payload.get("LawSearch")
    if not isinstance(law_search, dict):
        raise ValueError("current_law_list payload must contain 'LawSearch'")

    items = law_search.get("law", [])
    if isinstance(items, dict):
        items = [items]

    if not isinstance(items, list):
        raise ValueError("LawSearch.law must be a list or dict")

    return [item for item in items if isinstance(item, dict)]


def build_law_ref_from_search_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "law_name": item.get("법령명한글"),
        "law_id": item.get("법령ID"),
        "mst": item.get("법령일련번호"),
        "ef_yd": item.get("시행일자"),
        "kind_name": item.get("법령구분명"),
        "detail_link": item.get("법령상세링크"),
        "ministry_name": item.get("소관부처명"),
        "promulgation_date": item.get("공포일자"),
        "promulgation_no": item.get("공포번호"),
    }


def select_best_law_ref_from_search(
    payload: dict[str, Any],
    law_name: str,
) -> dict[str, Any] | None:
    items = get_law_items_from_search(payload)
    if not items:
        return None

    normalized_query = _normalize_name(law_name)

    exact_matches = []
    partial_matches = []

    for item in items:
        ref = build_law_ref_from_search_item(item)
        ref_name = _normalize_name(str(ref.get("law_name") or ""))

        if ref_name == normalized_query:
            exact_matches.append(ref)
        elif normalized_query in ref_name:
            partial_matches.append(ref)

    if exact_matches:
        return exact_matches[0]

    if partial_matches:
        return partial_matches[0]

    return build_law_ref_from_search_item(items[0])


def fetch_law_body_by_ref(
    registry: dict[str, Any],
    oc: str,
    law_ref: dict[str, Any],
) -> dict[str, Any]:
    runtime_params: dict[str, Any] = {"OC": oc}

    mst = law_ref.get("mst")
    ef_yd = law_ref.get("ef_yd")
    law_id = law_ref.get("law_id")

    # 가장 정확한 현재본 지정은 MST + efYd
    if mst and ef_yd:
        runtime_params["MST"] = str(mst)
        runtime_params["efYd"] = str(ef_yd)
    elif law_id:
        runtime_params["ID"] = str(law_id)
    else:
        raise ValueError("law_ref must contain either (mst + ef_yd) or law_id")

    request = build_request(
        registry,
        "law_current_detail",
        runtime_params,
    )
    payload = execute_json_request(request)
    _ensure_success_payload("law_current_detail", payload)
    return payload


def collect_root_law_body(
    registry: dict[str, Any],
    oc: str,
    law_name: str,
    save_dir: str | Path | None = None,
) -> dict[str, Any]:
    current_law_list = fetch_current_law_list(registry, oc, law_name)

    law_ref = select_best_law_ref_from_search(current_law_list, law_name)
    if law_ref is None:
        raise RuntimeError(f"No law candidate found for '{law_name}'")

    law_body = fetch_law_body_by_ref(registry, oc, law_ref)

    record = {
        "law_name": law_name,
        "law_ref": law_ref,
        "current_law_list": current_law_list,
        "law_body": law_body,
    }

    if save_dir is not None:
        base_dir = Path(save_dir)
        stem = _safe_filename(law_name)

        _write_json(
            base_dir / f"{stem}__law_current_list.json",
            current_law_list,
        )
        _write_json(
            base_dir / f"{stem}__law_current_detail.json",
            law_body,
        )
        _write_json(
            base_dir / f"{stem}__law_body_bundle.json",
            record,
        )

    return record


def collect_root_law_body_from_raw_record(
    registry: dict[str, Any],
    oc: str,
    raw_record: dict[str, Any],
    save_dir: str | Path | None = None,
) -> dict[str, Any]:
    law_name = str(raw_record.get("law_name") or "").strip()
    if not law_name:
        raise ValueError("raw_record must contain 'law_name'")

    current_law_list = raw_record.get("current_law_list")
    if not isinstance(current_law_list, dict):
        raise ValueError("raw_record must contain 'current_law_list' as dict")

    law_ref = select_best_law_ref_from_search(current_law_list, law_name)
    if law_ref is None:
        raise RuntimeError(f"No law candidate found for '{law_name}'")

    law_body = fetch_law_body_by_ref(registry, oc, law_ref)

    record = {
        "law_name": law_name,
        "law_ref": law_ref,
        "source_raw_record": {
            "system_diagram_ref": raw_record.get("system_diagram_ref"),
        },
        "law_body": law_body,
    }

    if save_dir is not None:
        base_dir = Path(save_dir)
        stem = _safe_filename(law_name)

        _write_json(
            base_dir / f"{stem}__law_current_detail.json",
            law_body,
        )
        _write_json(
            base_dir / f"{stem}__law_body_bundle.json",
            record,
        )

    return record