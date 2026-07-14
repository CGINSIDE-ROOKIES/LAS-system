from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.io_utils import _iter_jsonl, _read_json
from src.common.law_meta import build_law_uid
from src.collector.raw_law_collector import get_root_law_names


def build_law_uid_index(
    normalized_base_dir: str | Path = "data/normalized/01_current_law",
) -> dict[str, dict[str, str]]:
    normalized_base_dir = Path(normalized_base_dir)
    index: dict[str, dict[str, str]] = {}

    for path in sorted(normalized_base_dir.rglob("*__parsed_law.json")):
        payload = _read_json(path)
        law_name = str(payload.get("law_name") or "").strip()
        if not law_name:
            continue
        law_uid = build_law_uid(payload.get("law_id"), payload.get("mst"), law_name)
        index[law_uid] = {
            "law_name": law_name,
            "root_law_name": path.parent.name.replace("_", " ").strip() or law_name,
        }

    return index


def build_law_name_index(
    normalized_base_dir: str | Path = "data/normalized/01_current_law",
) -> dict[str, dict[str, str]]:
    normalized_base_dir = Path(normalized_base_dir)
    index: dict[str, dict[str, str]] = {}

    for path in sorted(normalized_base_dir.rglob("*__parsed_law.json")):
        payload = _read_json(path)
        law_name = str(payload.get("law_name") or "").strip()
        if not law_name:
            continue
        law_uid = build_law_uid(payload.get("law_id"), payload.get("mst"), law_name)
        index[law_name] = {
            "law_uid": law_uid,
            "law_name": law_name,
            "root_law_name": path.parent.name.replace("_", " ").strip() or law_name,
        }

    return index


def resolve_incremental_scope(
    *,
    scope: dict[str, Any],
    delta_events_path: str | Path,
    normalized_base_dir: str | Path = "data/normalized/01_current_law",
) -> dict[str, Any]:
    events = list(_iter_jsonl(Path(delta_events_path)))
    law_uid_index = build_law_uid_index(normalized_base_dir)
    law_name_index = build_law_name_index(normalized_base_dir)
    configured_roots = set(get_root_law_names(scope))

    changed_law_uids = sorted(
        {
            str(event.get("law_uid") or "").strip()
            for event in events
            if str(event.get("law_uid") or "").strip()
        }
    )
    deleted_law_uids = sorted(
        {
            str(event.get("law_uid") or "").strip()
            for event in events
            if str(event.get("event_type") or "").strip() == "law_deleted" and str(event.get("law_uid") or "").strip()
        }
    )

    changed_root_law_names: set[str] = set()
    for law_uid in changed_law_uids:
        entry = law_uid_index.get(law_uid)
        if entry and entry.get("root_law_name"):
            changed_root_law_names.add(entry["root_law_name"])
            continue

        law_name = next(
            (
                str(event.get("law_name") or "").strip()
                for event in events
                if str(event.get("law_uid") or "").strip() == law_uid and str(event.get("law_name") or "").strip()
            ),
            "",
        )
        name_entry = law_name_index.get(law_name)
        if name_entry and name_entry.get("root_law_name"):
            changed_root_law_names.add(name_entry["root_law_name"])
            continue
        if law_name in configured_roots:
            changed_root_law_names.add(law_name)

    return {
        "changed_law_uids": changed_law_uids,
        "deleted_law_uids": deleted_law_uids,
        "changed_root_law_names": sorted(changed_root_law_names),
        "needs_related_refresh": bool(changed_root_law_names),
        "needs_relation_refresh": bool(changed_root_law_names),
        "embed_collections": ["law_article", "legal_case"],
    }
