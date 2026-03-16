from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from src.common.io_utils import _write_json
from src.export.dataset_builder import build_and_write_datasets
from src.pipeline.law_pipeline import collect_all_root_law_families
from src.registry.load_registry import load_collection_scope, load_endpoint_registry
from src.registry.validate_registry import validate_collection_scope, validate_endpoint_registry

BASE_DIR = Path("data/experiments/labor_standards_act")
SCOPE_PATH = "config/experiments/collection_scope_labor_only.json"
SUB_ARTICLE_MODE = "all"


def _raise_if_invalid(name: str, result) -> None:
    for issue in result.warnings:
        print(f"[{name}][WARNING] {issue}")

    if result.has_errors:
        for issue in result.errors:
            print(f"[{name}][ERROR] {issue}")
        raise RuntimeError(f"{name} validation failed")


def main() -> None:
    load_dotenv()

    oc = os.environ.get("LAW_OC")
    if not oc:
        raise RuntimeError("LAW_OC environment variable is not set")

    scope = load_collection_scope(SCOPE_PATH)
    law_registry = load_endpoint_registry("config/endpoint_registry_law.yaml")

    _raise_if_invalid("collection_scope", validate_collection_scope(scope))
    _raise_if_invalid(
        "endpoint_registry_law",
        validate_endpoint_registry(law_registry),
    )

    family_results = collect_all_root_law_families(
        scope=scope,
        registry=law_registry,
        oc=oc,
        base_dir=BASE_DIR,
        max_roots=None,
        sub_article_mode=SUB_ARTICLE_MODE,
    )

    dataset_manifest = build_and_write_datasets(
        normalized_base_dir=BASE_DIR / "normalized" / "01_current_law",
        raw_related_base_dir=BASE_DIR / "raw" / "02_related_legal_docs",
        expanded_base_dir=BASE_DIR / "expanded" / "03_expanded_related_docs",
        output_dir=BASE_DIR / "dataset",
        max_chars=1200,
        overlap=150,
        text_variant="best",
        preserve_structure=True,
    )

    summary = {
        "scope_path": SCOPE_PATH,
        "base_dir": str(BASE_DIR),
        "root_count": len(family_results),
        "roots": family_results,
        "dataset_manifest": dataset_manifest,
        "sub_article_mode": SUB_ARTICLE_MODE,
    }

    _write_json(BASE_DIR / "manifest" / "labor_experiment_summary.json", summary)

    print("Labor experiment finished")
    print(summary)


if __name__ == "__main__":
    main()
