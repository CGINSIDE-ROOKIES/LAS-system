from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import argparse
import os

from dotenv import load_dotenv

from src.common.io_utils import _write_json
from src.export.dataset_builder import build_and_write_datasets
from src.export.dataset_validation import validate_appendix_merge_outputs
from src.pipeline.appendix_pipeline import run_appendix_asset_pipeline
from src.pipeline.full_collection_pipeline import run_full_collection
from src.registry.load_registry import load_collection_scope, load_endpoint_registry
from src.registry.validate_registry import validate_collection_scope, validate_endpoint_registry


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "y", "yes", "on"}


def _raise_if_invalid(name: str, result) -> None:
    for issue in result.warnings:
        print(f"[{name}][WARNING] {issue}")

    if result.has_errors:
        for issue in result.errors:
            print(f"[{name}][ERROR] {issue}")
        raise RuntimeError(f"{name} validation failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect current law + related docs + expanded relations and build datasets"
    )
    parser.add_argument("--scope", default="config/collection_scope.json")
    parser.add_argument("--law-registry", default="config/endpoint_registry_law.yaml")
    parser.add_argument("--related-registry", default="config/endpoint_registry_related.yaml")
    parser.add_argument("--base-dir", default="data")
    parser.add_argument("--sub-article-mode", default="none", choices=["none", "all"])
    parser.add_argument("--max-roots", type=int, default=None)
    parser.add_argument(
        "--related-target",
        dest="related_targets",
        action="append",
        default=None,
        help="Restrict related-doc collection to one or more targets. Repeat the option to add multiple.",
    )
    parser.add_argument("--max-pages-per-target", type=int, default=50)
    parser.add_argument("--detail-limit-per-target", type=int, default=10000)
    parser.add_argument("--max-records-per-target", type=int, default=10000)
    parser.add_argument(
        "--rebuild-only",
        action="store_true",
        help="Skip live collection and only rebuild datasets from existing raw/normalized files.",
    )
    parser.add_argument(
        "--appendix-assets",
        action="store_true",
        help="Run appendix asset pipeline after collection.",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    scope = load_collection_scope(args.scope)
    law_registry = load_endpoint_registry(args.law_registry)
    related_registry = load_endpoint_registry(args.related_registry)

    _raise_if_invalid("collection_scope", validate_collection_scope(scope))
    _raise_if_invalid("endpoint_registry_law", validate_endpoint_registry(law_registry))
    _raise_if_invalid("endpoint_registry_related", validate_endpoint_registry(related_registry))

    base_dir = Path(args.base_dir)
    appendix_asset_result = None
    full_collection_summary = None

    if not args.rebuild_only:
        oc = os.environ.get("LAW_OC")
        if not oc:
            raise RuntimeError("LAW_OC environment variable is not set. Use --rebuild-only to reuse cached payloads.")

        full_collection_summary = run_full_collection(
            scope=scope,
            law_registry=law_registry,
            related_registry=related_registry,
            oc=oc,
            base_dir=base_dir,
            max_roots=args.max_roots,
            sub_article_mode=args.sub_article_mode,
            related_targets=args.related_targets,
            max_pages_per_target=args.max_pages_per_target,
            detail_limit_per_target=args.detail_limit_per_target,
            max_records_per_target=args.max_records_per_target,
        )

        if args.appendix_assets or _env_flag("ENABLE_APPENDIX_ASSET_PIPELINE", default=False):
            appendix_asset_base_dir = base_dir / "normalized" / "01_current_law_appendix_assets"
            appendix_asset_result = run_appendix_asset_pipeline(
                normalized_appendix_base_dir=base_dir / "normalized" / "01_current_law_appendix",
                raw_asset_base_dir=base_dir / "raw" / "01_current_law_appendix_assets",
                normalized_asset_base_dir=appendix_asset_base_dir,
                output_dir=base_dir / "dataset",
                manifest_path=base_dir / "manifest" / "appendix_asset_pipeline_summary.json",
                download_assets=_env_flag("APPENDIX_DOWNLOAD_ASSETS", default=False),
                overwrite_assets=_env_flag("APPENDIX_OVERWRITE_ASSETS", default=False),
                timeout_sec=int(os.environ.get("APPENDIX_DOWNLOAD_TIMEOUT_SEC", "60")),
                download_base_url=os.environ.get("APPENDIX_DOWNLOAD_BASE_URL", "https://www.law.go.kr"),
                max_chars=1200,
                overlap=150,
                build_dataset=False,
            )

    dataset_manifest = build_and_write_datasets(
        normalized_base_dir=base_dir / "normalized" / "01_current_law",
        raw_related_base_dir=base_dir / "raw" / "02_related_legal_docs",
        expanded_base_dir=base_dir / "expanded" / "03_expanded_related_docs",
        output_dir=base_dir / "dataset",
        normalized_appendix_base_dir=base_dir / "normalized" / "01_current_law_appendix",
        normalized_appendix_asset_base_dir=(
            base_dir / "normalized" / "01_current_law_appendix_assets"
            if (base_dir / "normalized" / "01_current_law_appendix_assets").exists()
            else None
        ),
        max_chars=1200,
        overlap=150,
        text_variant="best",
        preserve_structure=True,
        merge_appendices_into_law_article=True,
        include_appendix_bundle_text_in_payload=True,
        write_legacy_appendix_datasets=False,
    )
    appendix_validation_summary = validate_appendix_merge_outputs(
        output_dir=base_dir / "dataset",
        manifest_path=base_dir / "manifest" / "appendix_validation_summary.json",
        dataset_manifest=dataset_manifest,
    )

    summary = {
        "scope_path": args.scope,
        "law_registry_path": args.law_registry,
        "related_registry_path": args.related_registry,
        "base_dir": str(base_dir),
        "rebuild_only": args.rebuild_only,
        "sub_article_mode": args.sub_article_mode,
        "max_roots": args.max_roots,
        "related_targets": args.related_targets,
        "max_pages_per_target": args.max_pages_per_target,
        "detail_limit_per_target": args.detail_limit_per_target,
        "max_records_per_target": args.max_records_per_target,
        "full_collection_summary": full_collection_summary,
        "dataset_manifest": dataset_manifest,
        "appendix_validation_summary": appendix_validation_summary,
        "appendix_asset_pipeline": appendix_asset_result,
    }
    _write_json(base_dir / "manifest" / "run_full_collection_summary.json", summary)

    print("Full collection workflow finished")
    print(summary)


if __name__ == "__main__":
    main()
