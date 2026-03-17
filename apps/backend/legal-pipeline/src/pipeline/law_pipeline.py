from __future__ import annotations

from pathlib import Path
from typing import Any

from src.collector.law_body_collector import fetch_law_body_by_ref
from src.collector.law_sub_article_collector import (
    SubArticleMode,
    collect_sub_articles_for_parsed_law,
)
from src.collector.raw_law_collector import (
    collect_root_law_raw,
    get_output_config,
    get_root_law_names,
)
from src.common.io_utils import _safe_filename, _write_json
from src.parser.appendix_parser import parse_appendix_bundle, save_parsed_appendix_bundle
from src.parser.law_parser import parse_law_body, save_parsed_law
from src.scope.resolver import select_family_law_refs_from_search


def get_allowed_law_levels(
    scope: dict[str, Any],
    file_id: str = "01_current_law",
) -> set[str]:
    output = get_output_config(scope, file_id=file_id)
    include_law_levels = output.get("include_law_levels", [])

    if not isinstance(include_law_levels, list):
        raise ValueError("include_law_levels must be a list")

    return {str(level).strip() for level in include_law_levels if str(level).strip()}


def get_part_policy(
    scope: dict[str, Any],
    file_id: str = "01_current_law",
) -> dict[str, list[str]]:
    output = get_output_config(scope, file_id=file_id)
    include_parts = output.get("include_parts", [])
    exclude_parts = output.get("exclude_parts", [])

    if not isinstance(include_parts, list):
        raise ValueError("include_parts must be a list")
    if not isinstance(exclude_parts, list):
        raise ValueError("exclude_parts must be a list")

    return {
        "include_parts": [
            str(item).strip()
            for item in include_parts
            if str(item).strip()
        ],
        "exclude_parts": [
            str(item).strip()
            for item in exclude_parts
            if str(item).strip()
        ],
    }


def should_include_descendants_from_system_diagram(
    scope: dict[str, Any],
    file_id: str = "01_current_law",
) -> bool:
    output = get_output_config(scope, file_id=file_id)
    return bool(output.get("include_descendants_from_system_diagram", False))


def _save_law_body_payloads(
    law_ref: dict[str, Any],
    law_body_response: dict[str, Any],
    save_dir: Path,
) -> dict[str, str]:
    stem = _safe_filename(str(law_ref.get("law_name") or "unnamed"))

    parsed_path = save_dir / f"{stem}__law_current_detail.parsed.json"
    response_path = save_dir / f"{stem}__law_current_detail.response.json"

    _write_json(parsed_path, law_body_response["parsed"])
    _write_json(response_path, law_body_response)

    return {
        "parsed_path": str(parsed_path),
        "response_path": str(response_path),
    }


def collect_root_law_family(
    scope: dict[str, Any],
    registry: dict[str, Any],
    oc: str,
    root_law_name: str,
    base_dir: str | Path = "data",
    sub_article_mode: SubArticleMode = "none",
) -> dict[str, Any]:
    base_dir = Path(base_dir)
    root_stem = _safe_filename(root_law_name)

    raw_root_dir = base_dir / "raw" / "01_current_law" / root_stem
    raw_body_dir = base_dir / "raw" / "01_current_law_body" / root_stem
    raw_sub_dir = base_dir / "raw" / "01_current_sub_article" / root_stem
    normalized_dir = base_dir / "normalized" / "01_current_law" / root_stem
    normalized_appendix_dir = base_dir / "normalized" / "01_current_law_appendix" / root_stem
    manifest_dir = base_dir / "manifest" / "01_current_law" / root_stem

    raw_record = collect_root_law_raw(
        registry=registry,
        oc=oc,
        law_name=root_law_name,
        save_dir=raw_root_dir,
    )

    allowed_levels = get_allowed_law_levels(scope)
    part_policy = get_part_policy(scope)
    include_descendants = should_include_descendants_from_system_diagram(scope)

    family_refs = select_family_law_refs_from_search(
        raw_record["current_law_list"],
        root_law_name=root_law_name,
        allowed_levels=allowed_levels,
        system_diagram_detail=raw_record.get("system_diagram_detail"),
        include_descendants_from_system_diagram=include_descendants,
    )

    collected_laws: list[dict[str, Any]] = []

    for law_ref in family_refs:
        law_body_response = fetch_law_body_by_ref(registry, oc, law_ref)
        law_body = law_body_response["parsed"]

        raw_body_paths = _save_law_body_payloads(
            law_ref=law_ref,
            law_body_response=law_body_response,
            save_dir=raw_body_dir,
        )

        parsed_law = parse_law_body(
            law_body,
            law_ref=law_ref,
            include_parts=part_policy["include_parts"],
            exclude_parts=part_policy["exclude_parts"],
        )
        parsed_path = save_parsed_law(parsed_law, normalized_dir)

        appendix_bundle = parse_appendix_bundle(law_body, law_ref=law_ref)
        parsed_appendix_path = save_parsed_appendix_bundle(
            appendix_bundle,
            normalized_appendix_dir,
        )

        sub_records = collect_sub_articles_for_parsed_law(
            registry=registry,
            oc=oc,
            law_ref=law_ref,
            parsed_law=parsed_law,
            mode=sub_article_mode,
            save_dir=raw_sub_dir / _safe_filename(str(law_ref.get("law_name") or "unnamed")),
        )

        collected_laws.append(
            {
                "law_name": law_ref.get("law_name"),
                "law_id": law_ref.get("law_id"),
                "mst": law_ref.get("mst"),
                "ef_yd": law_ref.get("ef_yd"),
                "kind_name": law_ref.get("kind_name"),
                "classified_level": law_ref.get("classified_level"),
                "scope_source": law_ref.get("scope_source"),
                "parsed_articles_count": parsed_law.get("articles_count"),
                "parsed_supplementary_count": parsed_law.get("supplementary_count"),
                "parsed_appendices_count": parsed_law.get("appendices_count"),
                "appendix_bundle_count": appendix_bundle.get("appendix_count"),
                "appendix_type_counts": appendix_bundle.get("appendix_type_counts", {}),
                "raw_body_parsed_path": raw_body_paths["parsed_path"],
                "raw_body_response_path": raw_body_paths["response_path"],
                "parsed_path": str(parsed_path),
                "parsed_appendix_path": str(parsed_appendix_path),
                "sub_article_count": len(sub_records),
            }
        )

    result = {
        "root_law_name": root_law_name,
        "family_count": len(collected_laws),
        "laws": collected_laws,
        "law_ref": raw_record.get("law_ref"),
        "scope_resolution": {
            "include_descendants_from_system_diagram": include_descendants,
            "source": "system_diagram" if include_descendants else "search_name_match",
        },
        "part_policy": part_policy,
    }

    _write_json(
        manifest_dir / f"{root_stem}__family_bundle.json",
        result,
    )

    return result


def collect_all_root_law_families(
    scope: dict[str, Any],
    registry: dict[str, Any],
    oc: str,
    base_dir: str | Path = "data",
    max_roots: int | None = None,
    sub_article_mode: SubArticleMode = "none",
) -> list[dict[str, Any]]:
    root_law_names = get_root_law_names(scope)
    if max_roots is not None:
        root_law_names = root_law_names[:max_roots]

    results: list[dict[str, Any]] = []
    for root_law_name in root_law_names:
        result = collect_root_law_family(
            scope=scope,
            registry=registry,
            oc=oc,
            root_law_name=root_law_name,
            base_dir=base_dir,
            sub_article_mode=sub_article_mode,
        )
        results.append(result)

    return results