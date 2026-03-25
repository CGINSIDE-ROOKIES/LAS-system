from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

from src.collector.law_delta_collector import collect_daily_law_delta
from src.collector.legal_case_hydrator import hydrate_canonical_cases_for_family_result
from src.collector.legal_doc_collector import collect_related_doc_candidates_for_family_result
from src.collector.related_doc_expander import collect_expanded_related_docs_for_family_result
from src.common.io_utils import _write_json
from src.export.dataset_builder import (
    build_and_write_datasets,
    build_incremental_dataset_patch,
    load_dataset_rows,
)
from src.pipeline.incremental_scope import resolve_incremental_scope
from src.pipeline.law_pipeline import collect_root_law_family
from src.registry.load_registry import load_collection_scope, load_endpoint_registry
from src.registry.validate_registry import validate_collection_scope, validate_endpoint_registry


def _raise_if_invalid(name: str, result) -> None:
    for issue in result.warnings:
        print(f"[{name}][WARNING] {issue}")
    if result.has_errors:
        for issue in result.errors:
            print(f"[{name}][ERROR] {issue}")
        raise RuntimeError(f"{name} validation failed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect daily law delta and rebuild dataset patches")
    parser.add_argument("--scope", default="config/collection_scope.json")
    parser.add_argument("--law-registry", default="config/endpoint_registry_law.yaml")
    parser.add_argument("--related-registry", default="config/endpoint_registry_related.yaml")
    parser.add_argument("--base-dir", default="data")
    parser.add_argument("--reg-dt", required=True)
    parser.add_argument("--sub-article-mode", default="none", choices=["none", "all"])
    parser.add_argument("--skip-related-refresh", action="store_true")
    parser.add_argument("--skip-law-to-law-relations", action="store_true")
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument("--upload-dry-run", action="store_true")
    return parser.parse_args()


def _run_subprocess(cmd: list[str]) -> None:
    result = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def _build_filtered_appendix_asset_base_dir(
    appendix_asset_base_dir: Path | None,
    *,
    excluded_root_law_names: list[str],
) -> tuple[Path | None, tempfile.TemporaryDirectory[str] | None]:
    if appendix_asset_base_dir is None or not appendix_asset_base_dir.exists():
        return None, None
    if not excluded_root_law_names:
        return appendix_asset_base_dir, None

    excluded = {name.strip() for name in excluded_root_law_names if name and name.strip()}
    if not excluded:
        return appendix_asset_base_dir, None

    temp_dir = tempfile.TemporaryDirectory(prefix="appendix-assets-filtered-")
    temp_base_dir = Path(temp_dir.name)

    for path in sorted(appendix_asset_base_dir.rglob("*__appendix_assets.parsed.json")):
        relative = path.relative_to(appendix_asset_base_dir)
        family_name = relative.parts[0].replace("_", " ").strip() if relative.parts else ""
        if family_name in excluded:
            continue
        destination = temp_base_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    return temp_base_dir, temp_dir


def main() -> None:
    load_dotenv()
    args = parse_args()

    scope = load_collection_scope(args.scope)
    law_registry = load_endpoint_registry(args.law_registry)
    related_registry = load_endpoint_registry(args.related_registry)

    _raise_if_invalid("collection_scope", validate_collection_scope(scope))
    _raise_if_invalid("endpoint_registry_law", validate_endpoint_registry(law_registry))
    _raise_if_invalid("endpoint_registry_related", validate_endpoint_registry(related_registry))

    oc = os.environ.get("LAW_OC")
    if not oc:
        raise RuntimeError("LAW_OC environment variable is not set")

    base_dir = Path(args.base_dir)
    dataset_dir = base_dir / "dataset"
    patch_dir = dataset_dir / "patches" / args.reg_dt

    previous_corpus_rows, previous_relation_rows = load_dataset_rows(dataset_dir)

    delta_summary = collect_daily_law_delta(
        registry=law_registry,
        oc=oc,
        reg_dt=args.reg_dt,
        base_dir=base_dir,
    )
    delta_events_path = base_dir / "delta" / args.reg_dt / "delta_events.jsonl"
    incremental_scope = resolve_incremental_scope(
        scope=scope,
        delta_events_path=delta_events_path,
        normalized_base_dir=base_dir / "normalized" / "01_current_law",
    )

    family_results: list[dict] = []
    for root_law_name in incremental_scope["changed_root_law_names"]:
        family_result = collect_root_law_family(
            scope=scope,
            registry=law_registry,
            oc=oc,
            root_law_name=root_law_name,
            base_dir=base_dir,
            sub_article_mode=args.sub_article_mode,
            clean_existing=True,
        )
        family_results.append(family_result)

        if args.skip_related_refresh:
            continue

        candidate_result = collect_related_doc_candidates_for_family_result(
            registry=related_registry,
            oc=oc,
            family_result=family_result,
            scope=scope,
            base_dir=base_dir / "raw" / "02_related_legal_docs",
        )
        effective_targets = list(candidate_result.get("targets", {}).keys())
        hydrate_canonical_cases_for_family_result(
            registry=related_registry,
            oc=oc,
            family_result=family_result,
            raw_related_base_dir=base_dir / "raw" / "02_related_legal_docs",
            targets=effective_targets,
        )
        collect_expanded_related_docs_for_family_result(
            scope=scope,
            family_result=family_result,
            raw_related_base_dir=base_dir / "raw" / "02_related_legal_docs",
            save_dir=base_dir / "expanded" / "03_expanded_related_docs",
            targets=effective_targets,
        )

    appendix_asset_base_dir = (
        base_dir / "normalized" / "01_current_law_appendix_assets"
        if (base_dir / "normalized" / "01_current_law_appendix_assets").exists()
        else None
    )
    filtered_appendix_asset_base_dir, temp_appendix_asset_dir = _build_filtered_appendix_asset_base_dir(
        appendix_asset_base_dir,
        excluded_root_law_names=incremental_scope["changed_root_law_names"],
    )

    try:
        dataset_manifest = build_and_write_datasets(
            normalized_base_dir=base_dir / "normalized" / "01_current_law",
            raw_related_base_dir=base_dir / "raw" / "02_related_legal_docs",
            expanded_base_dir=base_dir / "expanded" / "03_expanded_related_docs",
            output_dir=dataset_dir,
            normalized_appendix_base_dir=base_dir / "normalized" / "01_current_law_appendix",
            normalized_appendix_asset_base_dir=filtered_appendix_asset_base_dir,
            merge_appendices_into_law_article=True,
            include_appendix_bundle_text_in_payload=True,
            write_legacy_appendix_datasets=False,
            include_law_to_law_relations=not args.skip_law_to_law_relations,
        )
    finally:
        if temp_appendix_asset_dir is not None:
            temp_appendix_asset_dir.cleanup()
    current_corpus_rows, current_relation_rows = load_dataset_rows(dataset_dir)

    patch_manifest = build_incremental_dataset_patch(
        previous_corpus_rows=previous_corpus_rows,
        current_corpus_rows=current_corpus_rows,
        previous_relation_rows=previous_relation_rows,
        current_relation_rows=current_relation_rows,
        patch_dir=patch_dir,
        delta_batch_id=args.reg_dt,
    )

    if not args.skip_embed:
        _run_subprocess(
            [
                sys.executable,
                "scripts/embed_qdrant_incremental.py",
                "--dataset-patch-dir",
                str(patch_dir),
                "--delta-batch-id",
                args.reg_dt,
            ]
        )

        if args.upload_dry_run:
            _run_subprocess(
                [
                    sys.executable,
                    "scripts/upload/load_qdrant_incremental.py",
                    "--patch-dir",
                    str(base_dir / "handoff" / "qdrant_incremental" / args.reg_dt),
                    "--dry-run",
                ]
            )

    summary = {
        "reg_dt": args.reg_dt,
        "delta_summary": delta_summary,
        "incremental_scope": incremental_scope,
        "family_results": family_results,
        "dataset_manifest": dataset_manifest,
        "patch_manifest": patch_manifest,
    }
    _write_json(base_dir / "manifest" / f"incremental_update_{args.reg_dt}.json", summary)

    print("Incremental update workflow finished")
    print(summary)


if __name__ == "__main__":
    main()
