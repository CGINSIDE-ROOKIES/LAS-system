from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.env import load_backend_env
from src.collector.law_delta_collector import collect_daily_law_delta
from src.collector.legal_case_hydrator import hydrate_canonical_cases_for_family_result
from src.collector.legal_doc_collector import collect_related_doc_candidates_for_family_result
from src.collector.related_doc_expander import collect_expanded_related_docs_for_family_result
from src.common.io_utils import _write_json, _write_jsonl
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


def _log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[incremental][{timestamp}] {message}", flush=True)


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
    parser.add_argument("--skip-opensearch-upload", action="store_true")
    parser.add_argument("--opensearch-dry-run", action="store_true")
    return parser.parse_args()


def _run_subprocess(cmd: list[str]) -> None:
    _log(f"subprocess start: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    _log(f"subprocess done: {' '.join(cmd)}")


def _build_qdrant_incremental_commands(
    *,
    reg_dt: str,
    base_dir: Path,
    patch_dir: Path,
    skip_embed: bool,
    upload_dry_run: bool,
) -> list[list[str]]:
    if skip_embed:
        return []

    commands = [
        [
            sys.executable,
            "scripts/embed_qdrant_incremental.py",
            "--dataset-patch-dir",
            str(patch_dir),
            "--delta-batch-id",
            reg_dt,
        ]
    ]
    if upload_dry_run:
        commands.append(
            [
                sys.executable,
                "scripts/upload/load_qdrant_incremental.py",
                "--patch-dir",
                str(base_dir / "handoff" / "qdrant_incremental" / reg_dt),
                "--dry-run",
            ]
        )
    return commands


def _build_opensearch_incremental_command(
    *,
    reg_dt: str,
    base_dir: Path,
    patch_dir: Path,
    skip_opensearch_upload: bool,
    opensearch_dry_run: bool,
) -> list[str] | None:
    if skip_opensearch_upload:
        return None

    command = [
        sys.executable,
        "scripts/upload/load_opensearch_incremental.py",
        "--dataset-patch-dir",
        str(patch_dir),
        "--output-dir",
        str(base_dir / "handoff" / "opensearch_incremental" / reg_dt),
    ]
    if opensearch_dry_run:
        command.append("--dry-run")
    return command


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


def _build_empty_patch_manifest(*, patch_dir: Path, delta_batch_id: str) -> dict:
    patch_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(patch_dir / "legal_corpus.upsert.jsonl", [])
    _write_jsonl(patch_dir / "legal_corpus.delete.jsonl", [])
    _write_jsonl(patch_dir / "legal_relations.upsert.jsonl", [])
    _write_jsonl(patch_dir / "legal_relations.delete.jsonl", [])

    delta_manifest = {
        "delta_batch_id": delta_batch_id,
        "legal_corpus_upsert_count": 0,
        "legal_corpus_delete_count": 0,
        "legal_relations_upsert_count": 0,
        "legal_relations_delete_count": 0,
    }
    _write_json(patch_dir / "delta_manifest.json", delta_manifest)

    return {
        "patch_dir": str(patch_dir),
        "delta_batch_id": delta_batch_id,
        "legal_corpus_upsert_count": 0,
        "legal_corpus_delete_count": 0,
        "legal_relations_upsert_count": 0,
        "legal_relations_delete_count": 0,
    }


def main() -> None:
    load_backend_env()
    args = parse_args()
    _log(
        "workflow start"
        f" reg_dt={args.reg_dt}"
        f" skip_related_refresh={args.skip_related_refresh}"
        f" skip_embed={args.skip_embed}"
        f" skip_opensearch_upload={args.skip_opensearch_upload}"
        f" opensearch_dry_run={args.opensearch_dry_run}"
    )

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

    _log(f"loading previous dataset rows from {dataset_dir}")
    previous_corpus_rows, previous_relation_rows = load_dataset_rows(dataset_dir)
    _log(
        "loaded previous dataset rows"
        f" corpus={len(previous_corpus_rows)}"
        f" relations={len(previous_relation_rows)}"
    )

    _log(f"collecting daily law delta for reg_dt={args.reg_dt}")
    delta_summary = collect_daily_law_delta(
        registry=law_registry,
        oc=oc,
        reg_dt=args.reg_dt,
        base_dir=base_dir,
    )
    _log(
        "daily law delta collected"
        f" event_count={delta_summary.get('event_count')}"
        f" changed_law_count={delta_summary.get('changed_law_count')}"
    )
    delta_events_path = base_dir / "delta" / args.reg_dt / "delta_events.jsonl"
    _log(f"resolving incremental scope from {delta_events_path}")
    incremental_scope = resolve_incremental_scope(
        scope=scope,
        delta_events_path=delta_events_path,
        normalized_base_dir=base_dir / "normalized" / "01_current_law",
    )
    changed_root_law_names = incremental_scope["changed_root_law_names"]
    _log(
        "incremental scope resolved"
        f" changed_root_law_count={len(changed_root_law_names)}"
        f" changed_root_laws={changed_root_law_names}"
    )

    if not changed_root_law_names:
        _log("no changed root laws matched current scope; skipping dataset rebuild and uploads")
        patch_manifest = _build_empty_patch_manifest(
            patch_dir=patch_dir,
            delta_batch_id=args.reg_dt,
        )
        summary = {
            "reg_dt": args.reg_dt,
            "delta_summary": delta_summary,
            "incremental_scope": incremental_scope,
            "family_results": [],
            "dataset_manifest": None,
            "patch_manifest": patch_manifest,
            "skip_embed": args.skip_embed,
            "upload_dry_run": args.upload_dry_run,
            "skip_opensearch_upload": args.skip_opensearch_upload,
            "opensearch_dry_run": args.opensearch_dry_run,
            "opensearch_output_dir": str(base_dir / "handoff" / "opensearch_incremental" / args.reg_dt),
            "skipped": True,
            "skip_reason": "no_changed_root_laws_in_scope",
        }
        _write_json(base_dir / "manifest" / f"incremental_update_{args.reg_dt}.json", summary)
        _log(f"workflow summary written to {base_dir / 'manifest' / f'incremental_update_{args.reg_dt}.json'}")
        _log("incremental update workflow finished")
        print(summary)
        return

    family_results: list[dict] = []
    for idx, root_law_name in enumerate(changed_root_law_names, start=1):
        _log(f"[{idx}/{len(changed_root_law_names)}] collecting root law family: {root_law_name}")
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
        _log(f"[{idx}/{len(changed_root_law_names)}] root law family collected: {root_law_name}")

        if args.skip_related_refresh:
            _log(f"[{idx}/{len(changed_root_law_names)}] related refresh skipped: {root_law_name}")
            continue

        _log(f"[{idx}/{len(changed_root_law_names)}] collecting related doc candidates: {root_law_name}")
        candidate_result = collect_related_doc_candidates_for_family_result(
            registry=related_registry,
            oc=oc,
            family_result=family_result,
            scope=scope,
            base_dir=base_dir / "raw" / "02_related_legal_docs",
        )
        effective_targets = list(candidate_result.get("targets", {}).keys())
        _log(
            f"[{idx}/{len(changed_root_law_names)}] related doc candidates collected:"
            f" root_law={root_law_name}"
            f" targets={effective_targets}"
        )
        _log(f"[{idx}/{len(changed_root_law_names)}] hydrating canonical cases: {root_law_name}")
        hydrate_canonical_cases_for_family_result(
            registry=related_registry,
            oc=oc,
            family_result=family_result,
            raw_related_base_dir=base_dir / "raw" / "02_related_legal_docs",
            targets=effective_targets,
        )
        _log(f"[{idx}/{len(changed_root_law_names)}] canonical cases hydrated: {root_law_name}")
        _log(f"[{idx}/{len(changed_root_law_names)}] collecting expanded related docs: {root_law_name}")
        collect_expanded_related_docs_for_family_result(
            scope=scope,
            family_result=family_result,
            raw_related_base_dir=base_dir / "raw" / "02_related_legal_docs",
            save_dir=base_dir / "expanded" / "03_expanded_related_docs",
            targets=effective_targets,
        )
        _log(f"[{idx}/{len(changed_root_law_names)}] expanded related docs collected: {root_law_name}")

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
        _log("building dataset outputs")
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
        _log(
            "dataset outputs built"
            f" legal_corpus_count={dataset_manifest.get('legal_corpus_count')}"
            f" legal_relations_count={dataset_manifest.get('legal_relations_count')}"
        )
    finally:
        if temp_appendix_asset_dir is not None:
            temp_appendix_asset_dir.cleanup()
            _log("temporary appendix asset directory cleaned up")
    _log(f"reloading current dataset rows from {dataset_dir}")
    current_corpus_rows, current_relation_rows = load_dataset_rows(dataset_dir)
    _log(
        "loaded current dataset rows"
        f" corpus={len(current_corpus_rows)}"
        f" relations={len(current_relation_rows)}"
    )

    _log(f"building dataset patch into {patch_dir}")
    patch_manifest = build_incremental_dataset_patch(
        previous_corpus_rows=previous_corpus_rows,
        current_corpus_rows=current_corpus_rows,
        previous_relation_rows=previous_relation_rows,
        current_relation_rows=current_relation_rows,
        patch_dir=patch_dir,
        delta_batch_id=args.reg_dt,
    )
    _log(
        "dataset patch built"
        f" corpus_upserts={patch_manifest.get('legal_corpus_upsert_count')}"
        f" corpus_deletes={patch_manifest.get('legal_corpus_delete_count')}"
        f" relation_upserts={patch_manifest.get('legal_relations_upsert_count')}"
        f" relation_deletes={patch_manifest.get('legal_relations_delete_count')}"
    )

    for command in _build_qdrant_incremental_commands(
        reg_dt=args.reg_dt,
        base_dir=base_dir,
        patch_dir=patch_dir,
        skip_embed=args.skip_embed,
        upload_dry_run=args.upload_dry_run,
    ):
        _run_subprocess(command)

    opensearch_command = _build_opensearch_incremental_command(
        reg_dt=args.reg_dt,
        base_dir=base_dir,
        patch_dir=patch_dir,
        skip_opensearch_upload=args.skip_opensearch_upload,
        opensearch_dry_run=args.opensearch_dry_run,
    )
    if opensearch_command is not None:
        _run_subprocess(opensearch_command)

    summary = {
        "reg_dt": args.reg_dt,
        "delta_summary": delta_summary,
        "incremental_scope": incremental_scope,
        "family_results": family_results,
        "dataset_manifest": dataset_manifest,
        "patch_manifest": patch_manifest,
        "skip_embed": args.skip_embed,
        "upload_dry_run": args.upload_dry_run,
        "skip_opensearch_upload": args.skip_opensearch_upload,
        "opensearch_dry_run": args.opensearch_dry_run,
        "opensearch_output_dir": str(base_dir / "handoff" / "opensearch_incremental" / args.reg_dt),
    }
    _write_json(base_dir / "manifest" / f"incremental_update_{args.reg_dt}.json", summary)

    _log(f"workflow summary written to {base_dir / 'manifest' / f'incremental_update_{args.reg_dt}.json'}")
    _log("incremental update workflow finished")
    print(summary)


if __name__ == "__main__":
    main()
