from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from src.common.io_utils import _safe_filename, _write_json, _write_jsonl
from src.common.law_meta import build_law_uid
from src.common.payload_utils import _first_non_empty, _walk_objects
from src.core.http_client import execute_api_request
from src.core.request_builder import build_request


def _normalize_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _normalize_article_key(value: Any) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    return text.replace("제", "").replace("조", "").strip() or None


def _extract_rows(payload: dict[str, Any], preferred_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]

    rows: list[dict[str, Any]] = []
    for obj in _walk_objects(payload):
        if not isinstance(obj, dict):
            continue
        law_id = _first_non_empty(obj, "law_id", "법령ID", "changed_law_id", "deleted_law_id", "ID")
        law_name = _first_non_empty(obj, "law_name", "법령명", "법령명한글")
        if law_id in (None, "") and law_name in (None, ""):
            continue
        rows.append(dict(obj))
    return rows


def _event_from_row(row: dict[str, Any], *, event_type: str, source_endpoint: str, event_date: str) -> dict[str, Any]:
    law_id = _normalize_text(
        _first_non_empty(row, "law_id", "changed_law_id", "deleted_law_id", "법령ID", "ID")
    )
    mst = _normalize_text(_first_non_empty(row, "mst", "MST", "법령일련번호"))
    law_name = _normalize_text(_first_non_empty(row, "law_name", "법령명", "법령명한글"))
    article_key = _normalize_article_key(
        _first_non_empty(row, "article_key", "article_no", "changed_jo", "조문번호", "JO")
    )
    effective_date = _normalize_text(
        _first_non_empty(
            row,
            "effective_date",
            "enforcement_date",
            "jo_effective_date",
            "시행일자",
            "efYd",
        )
    )
    change_type = _normalize_text(_first_non_empty(row, "change_type", "change_reason", "변경사유"))
    law_uid = build_law_uid(law_id, mst, law_name)
    event_id = "::".join(
        [
            "delta",
            event_type,
            law_uid,
            article_key or "all",
            event_date,
        ]
    )
    return {
        "event_id": event_id,
        "event_date": event_date,
        "event_type": event_type,
        "law_id": law_id,
        "mst": mst,
        "law_name": law_name,
        "law_uid": law_uid,
        "article_key": article_key,
        "effective_date": effective_date,
        "change_type": change_type,
        "source_endpoint": source_endpoint,
    }


def _fetch_endpoint_payload(
    registry: dict[str, Any],
    endpoint_key: str,
    *,
    oc: str,
    runtime_params: dict[str, Any],
) -> dict[str, Any]:
    request = build_request(
        registry=registry,
        endpoint_key=endpoint_key,
        runtime_params={"OC": oc, **runtime_params},
    )
    result = execute_api_request(request)
    payload = result["parsed"]
    if not isinstance(payload, dict):
        raise RuntimeError(f"{endpoint_key} parsed payload must be dict")
    payload = dict(payload)
    payload["_response_url"] = result["url"]
    payload["_response_format"] = result["format"]
    payload["_response_content_type"] = result["content_type"]
    return payload


def collect_daily_law_delta(
    registry: dict[str, Any],
    oc: str,
    *,
    reg_dt: str,
    base_dir: str | Path = "data",
) -> dict[str, Any]:
    base_dir = Path(base_dir)
    delta_dir = base_dir / "delta" / reg_dt

    law_change_payload = _fetch_endpoint_payload(
        registry,
        "law_change_daily",
        oc=oc,
        runtime_params={"regDt": reg_dt},
    )
    article_change_payload = _fetch_endpoint_payload(
        registry,
        "law_article_change_daily",
        oc=oc,
        runtime_params={"regDt": reg_dt},
    )
    delete_payload = _fetch_endpoint_payload(
        registry,
        "law_delete_daily",
        oc=oc,
        runtime_params={"delDt": reg_dt},
    )

    _write_json(delta_dir / "daily_law_changes.raw.json", law_change_payload)
    _write_json(delta_dir / "daily_article_changes.raw.json", article_change_payload)
    _write_json(delta_dir / "daily_law_deletes.raw.json", delete_payload)

    events: list[dict[str, Any]] = []
    events.extend(
        _event_from_row(row, event_type="law_changed", source_endpoint="law_change_daily", event_date=reg_dt)
        for row in _extract_rows(law_change_payload, ("changed_laws",))
    )
    events.extend(
        _event_from_row(row, event_type="article_changed", source_endpoint="law_article_change_daily", event_date=reg_dt)
        for row in _extract_rows(article_change_payload, ("changed_articles",))
    )
    events.extend(
        _event_from_row(row, event_type="law_deleted", source_endpoint="law_delete_daily", event_date=reg_dt)
        for row in _extract_rows(delete_payload, ("deleted_laws",))
    )

    deduped: dict[str, dict[str, Any]] = {}
    for event in events:
        deduped[event["event_id"]] = event
    events = sorted(deduped.values(), key=lambda row: row["event_id"])

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[event["law_uid"]].append(event)

    changed_queue = [
        {
            "law_uid": law_uid,
            "law_id": rows[0].get("law_id"),
            "mst": rows[0].get("mst"),
            "law_name": rows[0].get("law_name"),
            "event_types": sorted({str(item.get("event_type") or "") for item in rows if str(item.get("event_type") or "")}),
            "article_keys": sorted({str(item.get("article_key") or "") for item in rows if str(item.get("article_key") or "")}),
            "event_count": len(rows),
        }
        for law_uid, rows in sorted(grouped.items())
    ]

    _write_jsonl(delta_dir / "delta_events.jsonl", events)
    _write_jsonl(delta_dir / "changed_law_queue.jsonl", changed_queue)

    summary = {
        "reg_dt": reg_dt,
        "event_count": len(events),
        "changed_law_count": len(changed_queue),
        "delta_dir": str(delta_dir),
    }
    _write_json(delta_dir / f"{_safe_filename(reg_dt)}__delta_summary.json", summary)
    return summary
