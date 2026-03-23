from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.io_utils import (
    _iter_jsonl,
    _safe_filename,
    _write_json,
    _write_jsonl,
)
from src.common.law_meta import build_law_uid, normalize_identifier_token
from src.common.payload_utils import (
    _ensure_success_payload,
    _first_non_empty,
    _walk_objects,
)
from src.core.http_client import execute_api_request, execute_json_request
from src.core.request_builder import build_request
from src.scope.resolver import is_allowed_level

RELATED_OUTPUT_FILE_ID = "02_related_legal_docs"

TARGET_CONFIGS = {
    "prec": {
        "list_endpoint": "precedent_list",
        "detail_endpoint": "precedent_detail",
    },
    "detc": {
        "list_endpoint": "constitutional_list",
        "detail_endpoint": "constitutional_detail",
    },
    "expc": {
        "list_endpoint": "interpretation_list",
        "detail_endpoint": "interpretation_detail",
    },
    "decc": {
        "list_endpoint": "admin_appeal_list",
        "detail_endpoint": "admin_appeal_detail",
    },
}

DOC_TYPE_LABELS = {
    "prec": "판례",
    "detc": "헌재결정례",
    "expc": "법령해석례",
    "decc": "행정심판례",
    "opinion_pending": "의견제시사례(보류)",
}

ID_KEYS_BY_TARGET = {
    "prec": ("판례일련번호", "판례정보일련번호"),
    "detc": ("헌재결정례일련번호",),
    "expc": ("법령해석례일련번호",),
    "decc": ("행정심판재결례일련번호", "행정심판례일련번호"),
}

TITLE_KEYS_BY_TARGET = {
    "prec": ("사건명",),
    "detc": ("사건명",),
    "expc": ("안건명",),
    "decc": ("사건명",),
}

NUMBER_KEYS_BY_TARGET = {
    "prec": ("사건번호",),
    "detc": ("사건번호",),
    "expc": ("안건번호",),
    "decc": ("사건번호",),
}

DETAIL_LINK_KEYS_BY_TARGET = {
    "prec": ("판례상세링크",),
    "detc": ("헌재결정례상세링크", "헌재결정례   상세링크"),
    "expc": ("법령해석례상세링크", "법령해석례   상세링크"),
    "decc": ("행정심판례상세링크", "행정심판례   상세링크"),
}

TEXT_KEYS_BY_TARGET = {
    "prec": ("판례내용", "판결요지", "판시사항"),
    "detc": ("결정요지", "판시사항", "전문"),
    "expc": ("회답", "해석내용", "답변"),
    "decc": ("이유", "재결요지", "주문"),
}

DOC_KIND_KEYS = (
    "문서종류",
    "문서구분",
    "문건종류",
    "문건구분",
    "안건종류",
    "안건구분",
    "유형",
    "구분",
    "종류",
)


def get_related_output_config(
    scope: dict[str, Any],
    file_id: str = RELATED_OUTPUT_FILE_ID,
) -> dict[str, Any]:
    outputs = scope.get("outputs", [])
    if not isinstance(outputs, list):
        raise ValueError("collection_scope.outputs must be a list")

    for output in outputs:
        if isinstance(output, dict) and output.get("file_id") == file_id:
            return output

    raise KeyError(f"Output config not found for file_id='{file_id}'")



def get_configured_doc_types(
    scope: dict[str, Any],
    file_id: str = RELATED_OUTPUT_FILE_ID,
) -> list[str]:
    output = get_related_output_config(scope, file_id=file_id)
    doc_types = output.get("doc_types", list(TARGET_CONFIGS.keys()))
    if not isinstance(doc_types, list):
        raise ValueError("doc_types must be a list")
    return [str(item).strip() for item in doc_types if str(item).strip()]



def get_configured_include_law_family_levels(
    scope: dict[str, Any],
    file_id: str = RELATED_OUTPUT_FILE_ID,
) -> set[str]:
    output = get_related_output_config(scope, file_id=file_id)
    levels = output.get("include_law_family_levels", [])
    if not isinstance(levels, list):
        raise ValueError("include_law_family_levels must be a list")
    return {str(item).strip() for item in levels if str(item).strip()}



def get_configured_exclude_doc_kinds(
    scope: dict[str, Any],
    file_id: str = RELATED_OUTPUT_FILE_ID,
) -> set[str]:
    output = get_related_output_config(scope, file_id=file_id)
    excluded = output.get("exclude_doc_kinds", [])
    if not isinstance(excluded, list):
        raise ValueError("exclude_doc_kinds must be a list")
    return {str(item).strip() for item in excluded if str(item).strip()}



def _get_registry_endpoint(registry: dict[str, Any], endpoint_key: str | None) -> dict[str, Any] | None:
    if endpoint_key is None:
        return None

    endpoints = registry.get("endpoints", {})
    if not isinstance(endpoints, dict):
        return None

    endpoint = endpoints.get(endpoint_key)
    if not isinstance(endpoint, dict):
        return None

    return endpoint



def resolve_selected_targets(
    scope: dict[str, Any] | None,
    registry: dict[str, Any],
    explicit_targets: list[str] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    desired = explicit_targets or (
        get_configured_doc_types(scope) if isinstance(scope, dict) else list(TARGET_CONFIGS.keys())
    )

    selected: list[str] = []
    skipped: list[dict[str, Any]] = []

    for target in desired:
        if target not in TARGET_CONFIGS:
            skipped.append(
                {
                    "target": target,
                    "reason": "unsupported_target",
                }
            )
            continue

        config = TARGET_CONFIGS[target]
        list_endpoint = _get_registry_endpoint(registry, config["list_endpoint"])
        if not list_endpoint or not bool(list_endpoint.get("enabled", False)):
            skipped.append(
                {
                    "target": target,
                    "reason": "list_endpoint_disabled_or_missing",
                }
            )
            continue

        selected.append(target)

    return selected, skipped



def _looks_like_item(target: str, obj: dict[str, Any]) -> bool:
    doc_id = _first_non_empty(obj, *ID_KEYS_BY_TARGET[target])
    if doc_id not in (None, ""):
        return True

    title = _first_non_empty(obj, *TITLE_KEYS_BY_TARGET[target])
    doc_number = _first_non_empty(obj, *NUMBER_KEYS_BY_TARGET[target])
    detail_link = _first_non_empty(obj, *DETAIL_LINK_KEYS_BY_TARGET[target])

    if title not in (None, "") and (doc_number not in (None, "") or detail_link not in (None, "")):
        return True

    text_value = _first_non_empty(obj, *TEXT_KEYS_BY_TARGET[target])
    if title not in (None, "") and text_value not in (None, ""):
        return True

    return False



def get_family_law_entries(
    family_result: dict[str, Any],
    allowed_levels: set[str] | None = None,
) -> list[dict[str, Any]]:
    laws = family_result.get("laws", [])
    if not isinstance(laws, list):
        raise ValueError("family_result.laws must be a list")

    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for law in laws:
        if not isinstance(law, dict):
            continue

        law_name = str(law.get("law_name") or "").strip()
        if not law_name or law_name in seen:
            continue

        classified_level = str(law.get("classified_level") or "").strip()
        if allowed_levels and not is_allowed_level(classified_level, allowed_levels):
            continue

        seen.add(law_name)
        results.append(law)

    return results



def build_search_params(
    target: str,
    law_name: str,
    page: int,
    display: int,
) -> dict[str, Any]:
    if target == "prec":
        return {
            "JO": law_name,
            "page": page,
            "display": display,
        }

    if target in {"detc", "expc", "decc"}:
        return {
            "query": law_name,
            "search": 2,
            "page": page,
            "display": display,
        }

    raise ValueError(f"Unsupported target: {target}")



def fetch_list_page(
    registry: dict[str, Any],
    oc: str,
    target: str,
    law_name: str,
    page: int = 1,
    display: int = 100,
) -> dict[str, Any]:
    endpoint_key = TARGET_CONFIGS[target]["list_endpoint"]
    runtime_params = {"OC": oc}
    runtime_params.update(build_search_params(target, law_name, page, display))

    request = build_request(
        registry=registry,
        endpoint_key=endpoint_key,
        runtime_params=runtime_params,
    )
    payload = execute_json_request(request)
    _ensure_success_payload(endpoint_key, payload)
    return payload



def extract_list_items(payload: dict[str, Any], target: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for obj in _walk_objects(payload):
        if not isinstance(obj, dict):
            continue
        if not _looks_like_item(target, obj):
            continue

        doc_id = _first_non_empty(obj, *ID_KEYS_BY_TARGET[target])
        title = _first_non_empty(obj, *TITLE_KEYS_BY_TARGET[target])
        doc_number = _first_non_empty(obj, *NUMBER_KEYS_BY_TARGET[target])

        dedup_key = "|".join(
            [
                str(doc_id or ""),
                str(title or ""),
                str(doc_number or ""),
            ]
        )
        if dedup_key in seen:
            continue

        seen.add(dedup_key)
        items.append(obj)

    return items



def _detect_doc_kind(item: dict[str, Any]) -> str | None:
    direct = _first_non_empty(item, *DOC_KIND_KEYS)
    if direct not in (None, ""):
        return str(direct).strip()

    for obj in _walk_objects(item):
        if not isinstance(obj, dict):
            continue
        direct = _first_non_empty(obj, *DOC_KIND_KEYS)
        if direct not in (None, ""):
            return str(direct).strip()

    return None



def should_exclude_doc_item(item: dict[str, Any], exclude_doc_kinds: set[str]) -> bool:
    if not exclude_doc_kinds:
        return False

    doc_kind = _detect_doc_kind(item)
    if not doc_kind:
        return False

    return any(kind in doc_kind for kind in exclude_doc_kinds)



def build_doc_ref(
    target: str,
    law_name: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    doc_id = _first_non_empty(item, *ID_KEYS_BY_TARGET[target])
    title = _first_non_empty(item, *TITLE_KEYS_BY_TARGET[target])
    doc_number = _first_non_empty(item, *NUMBER_KEYS_BY_TARGET[target])
    detail_link = _first_non_empty(item, *DETAIL_LINK_KEYS_BY_TARGET[target])
    doc_kind = _detect_doc_kind(item)

    return {
        "target": target,
        "related_law_name": law_name,
        "doc_id": str(doc_id) if doc_id is not None else None,
        "title": str(title) if title is not None else None,
        "doc_number": str(doc_number) if doc_number is not None else None,
        "detail_link": str(detail_link) if detail_link is not None else None,
        "doc_kind": str(doc_kind) if doc_kind is not None else None,
        "raw_item": item,
    }



def build_canonical_case_id(
    target: str,
    doc_id: Any,
    doc_number: Any = None,
    title: Any = None,
) -> str:
    primary = doc_id or doc_number or title or "unknown"
    return "::".join(
        [
            "case",
            normalize_identifier_token(target),
            normalize_identifier_token(primary),
        ]
    )



def _build_candidate_hit_id(
    root_law_name: str,
    source_law_name: str,
    target: str,
    ref: dict[str, Any],
    hit_rank: int,
) -> str:
    primary = ref.get("doc_id") or ref.get("doc_number") or ref.get("title") or hit_rank
    return "::".join(
        [
            "candidate",
            normalize_identifier_token(root_law_name),
            normalize_identifier_token(source_law_name),
            normalize_identifier_token(target),
            normalize_identifier_token(primary),
            str(hit_rank),
        ]
    )



def build_candidate_hit(
    *,
    root_law_name: str,
    law_entry: dict[str, Any],
    target: str,
    ref: dict[str, Any],
    source_file_path: str,
    hit_rank: int,
) -> dict[str, Any]:
    source_law_name = str(law_entry.get("law_name") or ref.get("related_law_name") or "").strip()
    doc_id = ref.get("doc_id")
    title = ref.get("title")
    doc_number = ref.get("doc_number")
    canonical_case_id = build_canonical_case_id(target, doc_id, doc_number, title)
    source_law_uid = build_law_uid(law_entry.get("law_id"), law_entry.get("mst"), source_law_name)
    root_law_uid = build_law_uid(None, None, root_law_name)

    return {
        "id": _build_candidate_hit_id(root_law_name, source_law_name, target, ref, hit_rank),
        "candidate_id": _build_candidate_hit_id(root_law_name, source_law_name, target, ref, hit_rank),
        "canonical_case_id": canonical_case_id,
        "canonical_id": canonical_case_id,
        "root_law_name": root_law_name,
        "root_law_uid": root_law_uid,
        "source_law_name": source_law_name,
        "source_law_uid": source_law_uid,
        "source_law_level": law_entry.get("classified_level"),
        "target": target,
        "doc_type_label": DOC_TYPE_LABELS[target],
        "doc_id": str(doc_id) if doc_id not in (None, "") else None,
        "title": str(title) if title not in (None, "") else None,
        "doc_number": str(doc_number) if doc_number not in (None, "") else None,
        "doc_kind": ref.get("doc_kind"),
        "detail_link": ref.get("detail_link"),
        "matched_query_law_name": source_law_name,
        "search_param_type": "JO" if target == "prec" else "query",
        "hit_rank": hit_rank,
        "source_file_path": source_file_path,
    }



def collect_list_refs_for_law_name(
    registry: dict[str, Any],
    oc: str,
    target: str,
    law_name: str,
    max_pages: int = 1,
    display: int = 100,
    save_dir: str | Path | None = None,
    exclude_doc_kinds: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    filtered_out = 0
    exclude_doc_kinds = exclude_doc_kinds or set()

    for page in range(1, max_pages + 1):
        payload = fetch_list_page(
            registry=registry,
            oc=oc,
            target=target,
            law_name=law_name,
            page=page,
            display=display,
        )

        list_path: Path | None = None
        if save_dir is not None:
            stem = _safe_filename(law_name)
            list_path = Path(save_dir) / f"{stem}__{target}__page_{page}__list.json"
            _write_json(list_path, payload)

        items = extract_list_items(payload, target)
        if not items:
            break

        for item in items:
            if should_exclude_doc_item(item, exclude_doc_kinds):
                filtered_out += 1
                continue

            ref = build_doc_ref(target, law_name, item)
            if list_path is not None:
                ref["source_file_path"] = str(list_path)
            dedup_key = (
                str(ref.get("doc_id") or ""),
                str(ref.get("title") or ""),
                str(ref.get("doc_number") or ""),
            )
            if dedup_key in seen:
                continue

            seen.add(dedup_key)
            refs.append(ref)

        if len(items) < display:
            break

    return refs, filtered_out



def _serialize_detail_response(result: dict[str, Any], target: str, ref: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "_response_format": result["format"],
        "_response_content_type": result["content_type"],
        "_response_url": result["url"],
        "_target": target,
        "_doc_ref": {
            "doc_id": ref.get("doc_id"),
            "title": ref.get("title"),
            "doc_number": ref.get("doc_number"),
            "detail_link": ref.get("detail_link"),
        },
    }

    parsed = result.get("parsed")
    if result["format"] in {"json", "xml"} and isinstance(parsed, dict):
        payload.update(parsed)
        return payload

    if result["format"] == "html" and isinstance(parsed, dict):
        html = parsed.get("html")
        text = parsed.get("text")
        if html not in (None, ""):
            payload["html"] = str(html)
        if text not in (None, ""):
            payload["text"] = str(text)
        return payload

    text = result.get("text")
    if text not in (None, ""):
        payload["text"] = str(text)
    return payload



def fetch_detail_by_ref(
    registry: dict[str, Any],
    oc: str,
    target: str,
    ref: dict[str, Any],
) -> dict[str, Any] | None:
    endpoint_key = TARGET_CONFIGS[target]["detail_endpoint"]
    if endpoint_key is None:
        return None

    endpoint = _get_registry_endpoint(registry, endpoint_key)
    if not endpoint or not bool(endpoint.get("enabled", False)):
        return None

    doc_id = ref.get("doc_id")
    if not doc_id:
        return None

    request = build_request(
        registry=registry,
        endpoint_key=endpoint_key,
        runtime_params={
            "OC": oc,
            "ID": str(doc_id),
        },
    )
    result = execute_api_request(request)
    if result["format"] == "json" and isinstance(result.get("parsed"), dict):
        _ensure_success_payload(endpoint_key, result["parsed"])
    return _serialize_detail_response(result, target, ref)



def collect_related_doc_candidates_for_family_result(
    registry: dict[str, Any],
    oc: str,
    family_result: dict[str, Any],
    scope: dict[str, Any] | None = None,
    targets: list[str] | None = None,
    max_pages_per_target: int = 1,
    base_dir: str | Path = "data/raw/02_related_legal_docs",
) -> dict[str, Any]:
    selected_targets, skipped_targets = resolve_selected_targets(scope, registry, targets)
    allowed_levels = (
        get_configured_include_law_family_levels(scope)
        if isinstance(scope, dict)
        else set()
    )
    exclude_doc_kinds = (
        get_configured_exclude_doc_kinds(scope)
        if isinstance(scope, dict)
        else set()
    )

    root_law_name = str(family_result.get("root_law_name") or "").strip()
    if not root_law_name:
        raise ValueError("family_result.root_law_name is required")

    family_law_entries = get_family_law_entries(family_result, allowed_levels=allowed_levels)
    family_law_names = [str(item.get("law_name") or "").strip() for item in family_law_entries]

    root_dir = Path(base_dir) / _safe_filename(root_law_name)
    candidate_hits: list[dict[str, Any]] = []

    result = {
        "root_law_name": root_law_name,
        "family_law_names": family_law_names,
        "selected_targets": selected_targets,
        "skipped_targets": skipped_targets,
        "policy": {
            "doc_types": get_configured_doc_types(scope) if isinstance(scope, dict) else list(TARGET_CONFIGS.keys()),
            "include_law_family_levels": sorted(allowed_levels),
            "exclude_doc_kinds": sorted(exclude_doc_kinds),
        },
        "candidate_hits_path": str(root_dir / "candidate_hits.jsonl"),
        "candidate_count": 0,
        "unique_case_count": 0,
        "targets": {},
        "errors": [],
    }

    for target in selected_targets:
        unique_case_ids: set[str] = set()
        target_summary = {
            "list_item_count": 0,
            "filtered_out_count": 0,
            "candidate_count": 0,
            "unique_case_count": 0,
            "detail_supported": bool(
                (_get_registry_endpoint(registry, TARGET_CONFIGS[target]["detail_endpoint"]) or {}).get("enabled", False)
            ),
            "searched_law_count": 0,
        }

        for law_entry in family_law_entries:
            law_name = str(law_entry.get("law_name") or "").strip()
            if not law_name:
                continue

            target_summary["searched_law_count"] += 1
            law_dir = root_dir / target / _safe_filename(law_name)

            try:
                refs, filtered_out = collect_list_refs_for_law_name(
                    registry=registry,
                    oc=oc,
                    target=target,
                    law_name=law_name,
                    max_pages=max_pages_per_target,
                    save_dir=law_dir,
                    exclude_doc_kinds=exclude_doc_kinds,
                )
            except Exception as exc:
                result["errors"].append(
                    {
                        "target": target,
                        "law_name": law_name,
                        "stage": "list",
                        "message": str(exc),
                    }
                )
                continue

            target_summary["filtered_out_count"] += filtered_out
            target_summary["list_item_count"] += len(refs)

            for hit_rank, ref in enumerate(refs, start=1):
                candidate = build_candidate_hit(
                    root_law_name=root_law_name,
                    law_entry=law_entry,
                    target=target,
                    ref=ref,
                    source_file_path=str(ref.get("source_file_path") or ""),
                    hit_rank=hit_rank,
                )
                candidate_hits.append(candidate)
                unique_case_ids.add(candidate["canonical_case_id"])

            target_summary["candidate_count"] += len(refs)
            target_summary["unique_case_count"] = len(unique_case_ids)

        result["targets"][target] = target_summary

    candidate_hits.sort(
        key=lambda row: (
            str(row.get("target") or ""),
            str(row.get("source_law_name") or ""),
            int(row.get("hit_rank") or 0),
            str(row.get("canonical_case_id") or ""),
        )
    )

    _write_jsonl(root_dir / "candidate_hits.jsonl", candidate_hits)

    unique_case_ids = {
        str(row.get("canonical_case_id") or "")
        for row in candidate_hits
        if str(row.get("canonical_case_id") or "")
    }
    result["candidate_count"] = len(candidate_hits)
    result["unique_case_count"] = len(unique_case_ids)

    _write_json(
        root_dir / f"{_safe_filename(root_law_name)}__related_docs_manifest.json",
        result,
    )

    return result



def load_candidate_hits(raw_related_root_dir: str | Path) -> list[dict[str, Any]]:
    return list(_iter_jsonl(Path(raw_related_root_dir) / "candidate_hits.jsonl"))



def collect_related_docs_for_family_result(
    registry: dict[str, Any],
    oc: str,
    family_result: dict[str, Any],
    scope: dict[str, Any] | None = None,
    targets: list[str] | None = None,
    max_pages_per_target: int = 1,
    detail_limit_per_target: int = 2,
    base_dir: str | Path = "data/raw/02_related_legal_docs",
) -> dict[str, Any]:
    result = collect_related_doc_candidates_for_family_result(
        registry=registry,
        oc=oc,
        family_result=family_result,
        scope=scope,
        targets=targets,
        max_pages_per_target=max_pages_per_target,
        base_dir=base_dir,
    )

    if detail_limit_per_target <= 0:
        return result

    try:
        from src.collector.legal_case_hydrator import hydrate_canonical_cases_for_family_result

        hydrate_result = hydrate_canonical_cases_for_family_result(
            registry=registry,
            oc=oc,
            family_result=family_result,
            raw_related_base_dir=base_dir,
            targets=targets,
            detail_limit_per_target=detail_limit_per_target,
        )
        result["canonical_case_count"] = hydrate_result.get("canonical_case_count", 0)
        result["hydrate_errors"] = hydrate_result.get("errors", [])
        result["canonical_cases_path"] = hydrate_result.get("canonical_cases_path")

        hydrate_targets = hydrate_result.get("targets", {})
        if isinstance(hydrate_targets, dict):
            for target, summary in hydrate_targets.items():
                target_summary = result.get("targets", {}).get(target)
                if not isinstance(target_summary, dict) or not isinstance(summary, dict):
                    continue
                detail_count = int(summary.get("detail_fetched_count") or 0) + int(summary.get("detail_reused_count") or 0)
                target_summary["detail_count"] = detail_count
                target_summary["detail_missing_count"] = int(summary.get("detail_missing_count") or 0)
    except Exception as exc:  # pragma: no cover - wrapper safety
        result.setdefault("hydrate_errors", []).append({"stage": "hydrate", "message": str(exc)})

    return result
