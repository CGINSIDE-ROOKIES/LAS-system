from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


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
        "detail_endpoint": None,
    },
    "decc": {
        "list_endpoint": "admin_appeal_list",
        "detail_endpoint": "admin_appeal_detail",
    },
}

ID_KEYS_BY_TARGET = {
    "prec": ("판례일련번호",),
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


def _first_non_empty(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", []):
            return value
    return None


def _walk_objects(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_objects(item)


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


def get_family_law_names(family_result: dict[str, Any]) -> list[str]:
    laws = family_result.get("laws", [])
    if not isinstance(laws, list):
        raise ValueError("family_result.laws must be a list")

    names: list[str] = []
    seen: set[str] = set()

    for law in laws:
        if not isinstance(law, dict):
            continue

        law_name = str(law.get("law_name") or "").strip()
        if not law_name or law_name in seen:
            continue

        seen.add(law_name)
        names.append(law_name)

    return names


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
    from src.core.http_client import execute_json_request
    from src.core.request_builder import build_request

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


def build_doc_ref(
    target: str,
    law_name: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    doc_id = _first_non_empty(item, *ID_KEYS_BY_TARGET[target])
    title = _first_non_empty(item, *TITLE_KEYS_BY_TARGET[target])
    doc_number = _first_non_empty(item, *NUMBER_KEYS_BY_TARGET[target])
    detail_link = _first_non_empty(item, *DETAIL_LINK_KEYS_BY_TARGET[target])

    return {
        "target": target,
        "related_law_name": law_name,
        "doc_id": str(doc_id) if doc_id is not None else None,
        "title": str(title) if title is not None else None,
        "doc_number": str(doc_number) if doc_number is not None else None,
        "detail_link": str(detail_link) if detail_link is not None else None,
        "raw_item": item,
    }


def collect_list_refs_for_law_name(
    registry: dict[str, Any],
    oc: str,
    target: str,
    law_name: str,
    max_pages: int = 1,
    display: int = 100,
    save_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for page in range(1, max_pages + 1):
        payload = fetch_list_page(
            registry=registry,
            oc=oc,
            target=target,
            law_name=law_name,
            page=page,
            display=display,
        )

        if save_dir is not None:
            stem = _safe_filename(law_name)
            _write_json(
                Path(save_dir) / f"{stem}__{target}__page_{page}__list.json",
                payload,
            )

        items = extract_list_items(payload, target)
        if not items:
            break

        for item in items:
            ref = build_doc_ref(target, law_name, item)
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

    return refs


def fetch_detail_by_ref(
    registry: dict[str, Any],
    oc: str,
    target: str,
    ref: dict[str, Any],
) -> dict[str, Any] | None:
    from src.core.http_client import execute_json_request
    from src.core.request_builder import build_request

    endpoint_key = TARGET_CONFIGS[target]["detail_endpoint"]
    if endpoint_key is None:
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
    payload = execute_json_request(request)
    _ensure_success_payload(endpoint_key, payload)
    return payload


def collect_related_docs_for_family_result(
    registry: dict[str, Any],
    oc: str,
    family_result: dict[str, Any],
    targets: list[str] | None = None,
    max_pages_per_target: int = 1,
    detail_limit_per_target: int = 2,
    base_dir: str | Path = "data/raw/02_related_legal_docs",
) -> dict[str, Any]:
    selected_targets = targets or ["prec", "detc", "expc", "decc"]

    root_law_name = str(family_result.get("root_law_name") or "").strip()
    if not root_law_name:
        raise ValueError("family_result.root_law_name is required")

    family_law_names = get_family_law_names(family_result)

    root_dir = Path(base_dir) / _safe_filename(root_law_name)
    seen_detail_ids: dict[str, set[str]] = {target: set() for target in selected_targets}
    remaining_budget: dict[str, int] = {
        target: detail_limit_per_target for target in selected_targets
    }

    result = {
        "root_law_name": root_law_name,
        "family_law_names": family_law_names,
        "targets": {},
        "errors": [],
    }

    for target in selected_targets:
        target_summary = {
            "list_item_count": 0,
            "detail_count": 0,
            "detail_supported": TARGET_CONFIGS[target]["detail_endpoint"] is not None,
        }

        for law_name in family_law_names:
            law_dir = root_dir / target / _safe_filename(law_name)

            try:
                refs = collect_list_refs_for_law_name(
                    registry=registry,
                    oc=oc,
                    target=target,
                    law_name=law_name,
                    max_pages=max_pages_per_target,
                    save_dir=law_dir,
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

            target_summary["list_item_count"] += len(refs)

            if TARGET_CONFIGS[target]["detail_endpoint"] is None:
                continue

            if remaining_budget[target] <= 0:
                continue

            for ref in refs:
                doc_id = str(ref.get("doc_id") or "").strip()
                if not doc_id or doc_id in seen_detail_ids[target]:
                    continue

                try:
                    payload = fetch_detail_by_ref(
                        registry=registry,
                        oc=oc,
                        target=target,
                        ref=ref,
                    )
                except Exception as exc:
                    result["errors"].append(
                        {
                            "target": target,
                            "law_name": law_name,
                            "stage": "detail",
                            "doc_id": doc_id,
                            "message": str(exc),
                        }
                    )
                    continue

                if payload is None:
                    continue

                seen_detail_ids[target].add(doc_id)
                target_summary["detail_count"] += 1
                remaining_budget[target] -= 1

                _write_json(
                    law_dir / f"{_safe_filename(doc_id)}__detail.json",
                    payload,
                )

                if remaining_budget[target] <= 0:
                    break

        result["targets"][target] = target_summary

    _write_json(
        root_dir / f"{_safe_filename(root_law_name)}__related_docs_manifest.json",
        result,
    )

    return result