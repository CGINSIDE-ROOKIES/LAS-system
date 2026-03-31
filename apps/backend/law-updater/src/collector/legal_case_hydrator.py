from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from src.collector.legal_doc_collector import (
    DOC_TYPE_LABELS,
    TARGET_CONFIGS,
    _get_registry_endpoint,
    fetch_detail_by_ref,
)
from src.common.io_utils import _iter_jsonl, _read_json, _safe_filename, _write_json, _write_jsonl



def _group_candidate_hits(candidate_hits: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidate_hits:
        canonical_case_id = str(row.get("canonical_case_id") or "").strip()
        if not canonical_case_id:
            continue
        grouped[canonical_case_id].append(row)
    return grouped



def _choose_primary_candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("target") or ""),
            int(row.get("hit_rank") or 0),
            str(row.get("source_law_name") or ""),
        ),
    )[0]



def _load_candidate_hits(root_dir: Path) -> list[dict[str, Any]]:
    return list(_iter_jsonl(root_dir / "candidate_hits.jsonl"))



def _detail_endpoint_enabled(registry: dict[str, Any], target: str) -> bool:
    endpoint_key = TARGET_CONFIGS[target]["detail_endpoint"]
    endpoint = _get_registry_endpoint(registry, endpoint_key)
    return bool(endpoint and endpoint.get("enabled", False))



def _existing_detail_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return _read_json(path)
    except Exception:
        return None



def hydrate_canonical_cases_for_family_result(
    registry: dict[str, Any],
    oc: str,
    family_result: dict[str, Any],
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    targets: list[str] | None = None,
    detail_limit_per_target: int = 10000,
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    root_law_name = str(family_result.get("root_law_name") or "").strip()
    if not root_law_name:
        raise ValueError("family_result.root_law_name is required")

    root_dir = Path(raw_related_base_dir) / _safe_filename(root_law_name)
    candidate_hits = _load_candidate_hits(root_dir)
    if targets:
        allowed_targets = set(targets)
        candidate_hits = [row for row in candidate_hits if row.get("target") in allowed_targets]

    grouped_hits = _group_candidate_hits(candidate_hits)
    detail_budget_by_target: dict[str, int] = defaultdict(lambda: detail_limit_per_target)
    canonical_rows: list[dict[str, Any]] = []

    result = {
        "root_law_name": root_law_name,
        "canonical_case_count": 0,
        "canonical_cases_path": str(root_dir / "canonical_cases.jsonl"),
        "targets": {},
        "errors": [],
    }

    target_summaries: dict[str, dict[str, int | bool]] = defaultdict(
        lambda: {
            "canonical_case_count": 0,
            "detail_supported": False,
            "detail_fetched_count": 0,
            "detail_reused_count": 0,
            "detail_missing_count": 0,
        }
    )

    for canonical_case_id in sorted(grouped_hits):
        hits = grouped_hits[canonical_case_id]
        primary = _choose_primary_candidate(hits)
        target = str(primary.get("target") or "").strip()
        if not target:
            continue

        target_summary = target_summaries[target]
        target_summary["detail_supported"] = _detail_endpoint_enabled(registry, target)
        target_summary["canonical_case_count"] = int(target_summary["canonical_case_count"] or 0) + 1

        detail_payload = None
        detail_path: Path | None = None
        detail_response_format: str | None = None
        detail_available = False
        detail_supported = bool(target_summary["detail_supported"])

        safe_case_id = _safe_filename(canonical_case_id)
        if detail_supported:
            detail_path = root_dir / "canonical" / target / f"{safe_case_id}__detail.json"
            if detail_path.exists() and not overwrite_existing:
                detail_payload = _existing_detail_payload(detail_path)
                if detail_payload is not None:
                    detail_available = True
                    detail_response_format = str(detail_payload.get("_response_format") or "") or None
                    target_summary["detail_reused_count"] = int(target_summary["detail_reused_count"] or 0) + 1

            if not detail_available and detail_budget_by_target[target] > 0:
                try:
                    detail_payload = fetch_detail_by_ref(
                        registry=registry,
                        oc=oc,
                        target=target,
                        ref=primary,
                    )
                except Exception as exc:
                    result["errors"].append(
                        {
                            "target": target,
                            "canonical_case_id": canonical_case_id,
                            "doc_id": primary.get("doc_id"),
                            "stage": "detail",
                            "message": str(exc),
                        }
                    )
                    detail_payload = None

                if detail_payload is not None and detail_path is not None:
                    _write_json(detail_path, detail_payload)
                    detail_available = True
                    detail_response_format = str(detail_payload.get("_response_format") or "") or None
                    detail_budget_by_target[target] -= 1
                    target_summary["detail_fetched_count"] = int(target_summary["detail_fetched_count"] or 0) + 1

        if detail_supported and not detail_available:
            target_summary["detail_missing_count"] = int(target_summary["detail_missing_count"] or 0) + 1

        canonical_row = {
            "id": canonical_case_id,
            "canonical_case_id": canonical_case_id,
            "canonical_id": canonical_case_id,
            "target": target,
            "doc_type_label": DOC_TYPE_LABELS[target],
            "doc_id": primary.get("doc_id"),
            "title": primary.get("title"),
            "doc_number": primary.get("doc_number"),
            "doc_kind": primary.get("doc_kind"),
            "detail_link": primary.get("detail_link"),
            "root_law_name": root_law_name,
            "root_law_uid": primary.get("root_law_uid"),
            "source_law_names": sorted(
                {
                    str(row.get("source_law_name") or "").strip()
                    for row in hits
                    if str(row.get("source_law_name") or "").strip()
                }
            ),
            "source_law_uids": sorted(
                {
                    str(row.get("source_law_uid") or "").strip()
                    for row in hits
                    if str(row.get("source_law_uid") or "").strip()
                }
            ),
            "candidate_refs": [
                {
                    "candidate_id": row.get("candidate_id"),
                    "source_law_name": row.get("source_law_name"),
                    "source_law_uid": row.get("source_law_uid"),
                    "hit_rank": row.get("hit_rank"),
                    "source_file_path": row.get("source_file_path"),
                }
                for row in sorted(hits, key=lambda item: (str(item.get("source_law_name") or ""), int(item.get("hit_rank") or 0)))
            ],
            "source_hit_count": len(hits),
            "detail_supported": detail_supported,
            "detail_available": detail_available,
            "detail_payload_path": str(detail_path) if detail_path is not None else None,
            "detail_response_format": detail_response_format,
        }
        canonical_rows.append(canonical_row)

    canonical_rows.sort(key=lambda row: (str(row.get("target") or ""), str(row.get("canonical_case_id") or "")))
    _write_jsonl(root_dir / "canonical_cases.jsonl", canonical_rows)

    result["canonical_case_count"] = len(canonical_rows)
    result["targets"] = {key: dict(value) for key, value in sorted(target_summaries.items())}

    _write_json(
        root_dir / f"{_safe_filename(root_law_name)}__canonical_cases_manifest.json",
        result,
    )

    return result
