from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from src.common.io_utils import _write_json
from src.export.dataset_builder import LawTextVariant, build_and_write_datasets
from src.pipeline.law_pipeline import collect_all_root_law_families
from src.registry.load_registry import load_collection_scope, load_endpoint_registry
from src.registry.validate_registry import (
    validate_collection_scope,
    validate_endpoint_registry,
)

DEFAULT_SCOPE_PATH = "config/experiments/collection_scope_labor_only.json"
DEFAULT_REGISTRY_PATH = "config/endpoint_registry_law.yaml"
DEFAULT_BASE_DIR = "data/experiments/labor_standards_act"
DEFAULT_VARIANTS: tuple[LawTextVariant, ...] = ("structure_preserved", "flat")


def _raise_if_invalid(name: str, result) -> None:
    for issue in result.warnings:
        print(f"[{name}][WARNING] {issue}")

    if result.has_errors:
        for issue in result.errors:
            print(f"[{name}][ERROR] {issue}")
        raise RuntimeError(f"{name} validation failed")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run labor-law-only collection and dataset build experiments.",
    )
    parser.add_argument(
        "--scope-path",
        default=DEFAULT_SCOPE_PATH,
        help=f"Collection scope JSON path (default: {DEFAULT_SCOPE_PATH})",
    )
    parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help=f"Law endpoint registry YAML path (default: {DEFAULT_REGISTRY_PATH})",
    )
    parser.add_argument(
        "--base-dir",
        default=DEFAULT_BASE_DIR,
        help=f"Experiment output base directory (default: {DEFAULT_BASE_DIR})",
    )
    parser.add_argument(
        "--sub-article-mode",
        choices=("none", "all"),
        default="all",
        help="Whether to additionally collect eflawjosub per parsed JO code.",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=1200,
        help="Chunk max character size for dataset export.",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=150,
        help="Chunk overlap size for dataset export.",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        default=list(DEFAULT_VARIANTS),
        choices=("structure_preserved", "flat"),
        help="Dataset text variants to export.",
    )
    return parser.parse_args()


def _normalize_variants(values: Sequence[str]) -> list[LawTextVariant]:
    variants: list[LawTextVariant] = []
    seen: set[str] = set()

    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        variants.append(normalized)  # type: ignore[arg-type]

    return variants or list(DEFAULT_VARIANTS)


def main() -> None:
    args = _parse_args()

    load_dotenv()

    oc = os.environ.get("LAW_OC")
    if not oc:
        raise RuntimeError("LAW_OC environment variable is not set")

    base_dir = Path(args.base_dir)
    variants = _normalize_variants(args.variants)

    scope = load_collection_scope(args.scope_path)
    law_registry = load_endpoint_registry(args.registry_path)

    _raise_if_invalid("collection_scope", validate_collection_scope(scope))
    _raise_if_invalid("endpoint_registry_law", validate_endpoint_registry(law_registry))

    print("Config validation passed")
    print("Running labor-law-only collection...")

    family_results = collect_all_root_law_families(
        scope=scope,
        registry=law_registry,
        oc=oc,
        base_dir=base_dir,
        max_roots=None,
        sub_article_mode=args.sub_article_mode,
    )

    dataset_manifests: dict[str, dict[str, object]] = {}
    normalized_base_dir = base_dir / "normalized" / "01_current_law"
    raw_related_base_dir = base_dir / "raw" / "02_related_legal_docs"
    expanded_base_dir = base_dir / "expanded" / "03_expanded_related_docs"

    for variant in variants:
        print(f"Building dataset variant: {variant}")
        dataset_manifests[variant] = build_and_write_datasets(
            normalized_base_dir=normalized_base_dir,
            raw_related_base_dir=raw_related_base_dir,
            expanded_base_dir=expanded_base_dir,
            output_dir=base_dir / "dataset" / variant,
            max_chars=args.max_chars,
            overlap=args.overlap,
            law_text_variant=variant,
        )

    summary = {
        "project": "labor_standards_act_experiment",
        "scope_path": args.scope_path,
        "registry_path": args.registry_path,
        "base_dir": str(base_dir),
        "sub_article_mode": args.sub_article_mode,
        "variants": variants,
        "family_results": family_results,
        "dataset_manifests": dataset_manifests,
    }

    _write_json(
        base_dir / "manifest" / "labor_experiment_summary.json",
        summary,
    )

    print("Labor experiment finished")
    print(f"Root families collected: {len(family_results)}")
    for variant, manifest in dataset_manifests.items():
        print(f"[{variant}] {manifest}")


if __name__ == "__main__":
    main()
