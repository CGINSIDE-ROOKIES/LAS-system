from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from src.export.dataset_builder import build_and_write_datasets
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


def _validate_related_registry_basic(registry: dict[str, Any]) -> None:
    """
    현재 validate_endpoint_registry()가 law registry 전용일 수 있으므로
    related registry는 main에서 기본 구조만 검증한다.
    """
    endpoints = registry.get("endpoints")
    if not isinstance(endpoints, dict):
        raise RuntimeError("endpoint_registry_related: 'endpoints' must be a mapping")

    required_endpoints = {
        "precedent_list",
        "precedent_detail",
        "constitutional_list",
        "constitutional_detail",
        "interpretation_list",
        "admin_appeal_list",
        "admin_appeal_detail",
    }

    missing = [key for key in required_endpoints if key not in endpoints]
    if missing:
        raise RuntimeError(
            f"endpoint_registry_related: missing required endpoints {missing}"
        )

    for endpoint_key in required_endpoints:
        endpoint = endpoints[endpoint_key]

        if not isinstance(endpoint, dict):
            raise RuntimeError(
                f"endpoint_registry_related.{endpoint_key} must be a dict"
            )

        if "path" not in endpoint:
            raise RuntimeError(
                f"endpoint_registry_related.{endpoint_key} missing 'path'"
            )

        if "target" not in endpoint:
            raise RuntimeError(
                f"endpoint_registry_related.{endpoint_key} missing 'target'"
            )

        if "required_params" not in endpoint:
            raise RuntimeError(
                f"endpoint_registry_related.{endpoint_key} missing 'required_params'"
            )

        enabled = endpoint.get("enabled", False)
        response_types = endpoint.get("response_types", [])

        if enabled and "JSON" not in response_types:
            raise RuntimeError(
                f"endpoint_registry_related.{endpoint_key} must support JSON when enabled"
            )


def main() -> None:
    load_dotenv()

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
    _validate_related_registry_basic(related_registry)

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

    print("Building JSONL dataset...")

    manifest = build_and_write_datasets(
        normalized_base_dir="data/normalized/01_current_law",
        raw_related_base_dir="data/raw/02_related_legal_docs",
        expanded_base_dir="data/expanded/03_expanded_related_docs",
        output_dir="data/dataset",
        max_chars=1200,
        overlap=150,
    )

    print("JSONL files created")
    print(manifest)


if __name__ == "__main__":
    main()