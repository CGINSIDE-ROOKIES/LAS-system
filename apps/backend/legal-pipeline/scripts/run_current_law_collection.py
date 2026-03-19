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
from src.pipeline.appendix_pipeline import run_appendix_asset_pipeline
from src.pipeline.law_pipeline import collect_all_root_law_families
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
    parser = argparse.ArgumentParser(description="Collect 01_current_law and build datasets")
    parser.add_argument("--scope", default="config/collection_scope.json")
    parser.add_argument("--base-dir", default="data")
    parser.add_argument("--sub-article-mode", default="none", choices=["none", "all"])
    parser.add_argument("--max-roots", type=int, default=None)
    parser.add_argument(
        "--rebuild-only",
        action="store_true",
        help="Skip live collection and only rebuild datasets/handoff from existing normalized/raw files.",
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
    law_registry = load_endpoint_registry("config/endpoint_registry_law.yaml")

    _raise_if_invalid("collection_scope", validate_collection_scope(scope))
    _raise_if_invalid("endpoint_registry_law", validate_endpoint_registry(law_registry))

    base_dir = Path(args.base_dir)
    appendix_asset_result = None
    family_results = []

    if not args.rebuild_only:
        oc = os.environ.get("LAW_OC")
        if not oc:
            raise RuntimeError("LAW_OC environment variable is not set. Use --rebuild-only to reuse cached payloads.")

        family_results = collect_all_root_law_families(
            scope=scope,
            registry=law_registry,
            oc=oc,
            base_dir=base_dir,
            max_roots=args.max_roots,
            sub_article_mode=args.sub_article_mode,
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

        # 추가
        merge_appendices_into_law_article=True,
        include_appendix_bundle_text_in_payload=True,
        write_legacy_appendix_datasets=False,
    )

    summary = {
        "scope_path": args.scope,
        "base_dir": str(base_dir),
        "rebuild_only": args.rebuild_only,
        "root_count": len(family_results),
        "roots": family_results,
        "dataset_manifest": dataset_manifest,
        "sub_article_mode": args.sub_article_mode,
        "appendix_asset_pipeline": appendix_asset_result,
    }
    _write_json(base_dir / "manifest" / "current_law_collection_summary.json", summary)

    print("Current-law collection workflow finished")
    print(summary)


if __name__ == "__main__":
    main()
