from __future__ import annotations

import os

from src.common.env import load_backend_env
from src.export.dataset_builder import build_and_write_datasets
from src.export.dataset_validation import validate_appendix_merge_outputs
from src.pipeline.appendix_pipeline import run_appendix_asset_pipeline
from src.pipeline.full_collection_pipeline import run_full_collection
from src.registry.load_registry import (
    load_collection_scope,
    load_endpoint_registry,
)
from src.registry.validate_registry import (
    validate_collection_scope,
    validate_endpoint_registry,
)



def _raise_if_invalid(name: str, result) -> None:
    for issue in result.warnings:
        print(f"[{name}][WARNING] {issue}")

    if result.has_errors:
        for issue in result.errors:
            print(f"[{name}][ERROR] {issue}")
        raise RuntimeError(f"{name} validation failed")



def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "y", "yes", "on"}



def main() -> None:
    load_backend_env()

    oc = os.environ.get("LAW_OC")
    if not oc:
        raise RuntimeError("LAW_OC environment variable is not set")

    scope = load_collection_scope()
    law_registry = load_endpoint_registry("config/endpoint_registry_law.yaml")
    related_registry = load_endpoint_registry("config/endpoint_registry_related.yaml")

    # config validation
    _raise_if_invalid("collection_scope", validate_collection_scope(scope))
    _raise_if_invalid(
        "endpoint_registry_law",
        validate_endpoint_registry(law_registry),
    )
    _raise_if_invalid(
        "endpoint_registry_related",
        validate_endpoint_registry(related_registry),
    )

    print("Config validation passed")
    print("Starting full collection...")

    result = run_full_collection(
        scope=scope,
        law_registry=law_registry,
        related_registry=related_registry,
        oc=oc,
        base_dir="data",
        max_roots=None,
        sub_article_mode="none",
        max_pages_per_target=50,
        detail_limit_per_target=10000,
        max_records_per_target=10000,
    )

    print("Collection finished")
    print("Root laws:", result["root_count"])

    appendix_asset_result = None
    appendix_asset_base_dir = "data/normalized/01_current_law_appendix_assets"
    if _env_flag("ENABLE_APPENDIX_ASSET_PIPELINE", default=False):
        appendix_asset_result = run_appendix_asset_pipeline(
            normalized_appendix_base_dir="data/normalized/01_current_law_appendix",
            raw_asset_base_dir="data/raw/01_current_law_appendix_assets",
            normalized_asset_base_dir=appendix_asset_base_dir,
            output_dir="data/dataset",
            manifest_path="data/manifest/appendix_asset_pipeline_summary.json",
            download_assets=_env_flag("APPENDIX_DOWNLOAD_ASSETS", default=False),
            overwrite_assets=_env_flag("APPENDIX_OVERWRITE_ASSETS", default=False),
            timeout_sec=int(os.environ.get("APPENDIX_DOWNLOAD_TIMEOUT_SEC", "60")),
            download_base_url=os.environ.get("APPENDIX_DOWNLOAD_BASE_URL", "https://www.law.go.kr"),
            max_chars=1200,
            overlap=150,
            build_dataset=False,
        )

    print("Building JSONL dataset...")

    manifest = build_and_write_datasets(
        normalized_base_dir="data/normalized/01_current_law",
        raw_related_base_dir="data/raw/02_related_legal_docs",
        expanded_base_dir="data/expanded/03_expanded_related_docs",
        output_dir="data/dataset",
        normalized_appendix_base_dir="data/normalized/01_current_law_appendix",
        normalized_appendix_asset_base_dir=(
            appendix_asset_base_dir if appendix_asset_result is not None else None
        ),
        max_chars=1200,
        overlap=150,
        merge_appendices_into_law_article=True,
        include_appendix_bundle_text_in_payload=True,
        write_legacy_appendix_datasets=True,
    )
    appendix_validation_summary = validate_appendix_merge_outputs(
        output_dir="data/dataset",
        manifest_path="data/manifest/appendix_validation_summary.json",
        dataset_manifest=manifest,
    )

    print("JSONL files created")
    print(manifest)
    print("Appendix merge validation finished")
    print(appendix_validation_summary)
    if appendix_asset_result is not None:
        print("Appendix asset pipeline finished")
        print(appendix_asset_result)


if __name__ == "__main__":
    main()
