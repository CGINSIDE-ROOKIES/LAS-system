from __future__ import annotations

from pathlib import Path
from typing import Any

from src.collector.legal_case_hydrator import hydrate_canonical_cases_for_family_result
from src.collector.legal_doc_collector import collect_related_doc_candidates_for_family_result
from src.collector.related_doc_expander import collect_expanded_related_docs_for_family_result
from src.common.io_utils import _write_json
from src.pipeline.law_pipeline import collect_all_root_law_families


def run_full_collection(
    scope: dict[str, Any],
    law_registry: dict[str, Any],
    related_registry: dict[str, Any],
    oc: str,
    base_dir: str | Path = "data",
    max_roots: int | None = None,
    sub_article_mode: str = "none",
    related_targets: list[str] | None = None,
    max_pages_per_target: int = 50,
    detail_limit_per_target: int = 10000,
    max_records_per_target: int = 10000,
) -> dict[str, Any]:
    family_results = collect_all_root_law_families(
        scope=scope,
        registry=law_registry,
        oc=oc,
        base_dir=base_dir,
        max_roots=max_roots,
        sub_article_mode=sub_article_mode,
    )

    summaries: list[dict[str, Any]] = []

    for family_result in family_results:
        candidate_result = collect_related_doc_candidates_for_family_result(
            registry=related_registry,
            oc=oc,
            family_result=family_result,
            scope=scope,
            targets=related_targets,
            max_pages_per_target=max_pages_per_target,
            base_dir=Path(base_dir) / "raw" / "02_related_legal_docs",
        )

        effective_targets = list(candidate_result.get("targets", {}).keys())

        hydrate_result = hydrate_canonical_cases_for_family_result(
            registry=related_registry,
            oc=oc,
            family_result=family_result,
            raw_related_base_dir=Path(base_dir) / "raw" / "02_related_legal_docs",
            targets=effective_targets,
            detail_limit_per_target=detail_limit_per_target,
        )

        expanded_result = collect_expanded_related_docs_for_family_result(
            scope=scope,
            family_result=family_result,
            raw_related_base_dir=Path(base_dir) / "raw" / "02_related_legal_docs",
            save_dir=Path(base_dir) / "expanded" / "03_expanded_related_docs",
            targets=effective_targets,
            max_records_per_target=max_records_per_target,
        )

        summaries.append(
            {
                "root_law_name": family_result["root_law_name"],
                "family_count": family_result["family_count"],
                "candidate_count": candidate_result.get("candidate_count", 0),
                "unique_case_count": candidate_result.get("unique_case_count", 0),
                "candidate_targets": candidate_result.get("targets", {}),
                "candidate_errors": candidate_result.get("errors", []),
                "canonical_case_count": hydrate_result.get("canonical_case_count", 0),
                "hydrate_targets": hydrate_result.get("targets", {}),
                "hydrate_errors": hydrate_result.get("errors", []),
                "expanded_count": expanded_result["expanded_count"],
                "expanded_targets": expanded_result["targets"],
                "expanded_errors": expanded_result["errors"],
            }
        )

    result = {
        "root_count": len(summaries),
        "roots": summaries,
    }

    _write_json(
        Path(base_dir) / "manifest" / "full_collection_summary.json",
        result,
    )

    return result
