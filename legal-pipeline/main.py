from __future__ import annotations

import os

from dotenv import load_dotenv

from src.export.dataset_builder import build_and_write_datasets
from src.pipeline.full_collection_pipeline import run_full_collection
from src.registry.load_registry import (
    load_collection_scope,
    load_endpoint_registry,
)


def main() -> None:
    load_dotenv()

    oc = os.environ.get("LAW_OC")
    if not oc:
        raise RuntimeError("LAW_OC environment variable is not set")

    scope = load_collection_scope()
    law_registry = load_endpoint_registry("config/endpoint_registry_law.yaml")
    related_registry = load_endpoint_registry("config/endpoint_registry_related.yaml")

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