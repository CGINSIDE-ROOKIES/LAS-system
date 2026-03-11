from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.collector.legal_doc_collector import collect_related_docs_for_family_result
from src.collector.related_doc_expander import collect_expanded_related_docs_for_family_result
from src.pipeline.law_pipeline import collect_all_root_law_families


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
        related_result = collect_related_docs_for_family_result(
            registry=related_registry,
            oc=oc,
            family_result=family_result,
            targets=related_targets,
            max_pages_per_target=max_pages_per_target,
            detail_limit_per_target=detail_limit_per_target,
            base_dir=Path(base_dir) / "raw" / "02_related_legal_docs",
        )

        expanded_result = collect_expanded_related_docs_for_family_result(
            scope=scope,
            family_result=family_result,
            raw_related_base_dir=Path(base_dir) / "raw" / "02_related_legal_docs",
            save_dir=Path(base_dir) / "expanded" / "03_expanded_related_docs",
            targets=related_targets,
            max_records_per_target=max_records_per_target,
        )

        summaries.append(
            {
                "root_law_name": family_result["root_law_name"],
                "family_count": family_result["family_count"],
                "related_targets": related_result["targets"],
                "related_errors": related_result["errors"],
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