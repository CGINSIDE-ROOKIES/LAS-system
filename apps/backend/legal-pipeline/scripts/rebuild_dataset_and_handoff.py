from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.io_utils import _write_json
from src.collector.expc_html_collector import hydrate_expc_related_prec_ids
from src.export.dataset_builder import build_and_write_datasets
from src.export.dataset_validation import validate_appendix_merge_outputs
from scripts.embed_qdrant_3collections import export_legal_relation_handoff


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild dataset and optional Qdrant handoff from existing raw/normalized files "
            "(current embedding targets: law_article, legal_case)"
        )
    )
    parser.add_argument("--base-dir", default="data")
    parser.add_argument("--skip-embed", action="store_true")
    parser.add_argument("--hydrate-expc-html", action="store_true")
    parser.add_argument("--overwrite-expc-html", action="store_true")
    parser.add_argument("--upload-dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=None)
    return parser.parse_args()


def _run_subprocess(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(cmd, cwd=REPO_ROOT, check=False, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")


def main() -> None:
    args = parse_args()
    base_dir = Path(args.base_dir)
    expc_html_summary = None

    if args.hydrate_expc_html:
        expc_html_summary = hydrate_expc_related_prec_ids(
            raw_related_base_dir=base_dir / "raw" / "02_related_legal_docs",
            overwrite=args.overwrite_expc_html,
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
        include_law_to_law_relations=True,
    )
    appendix_validation_summary = validate_appendix_merge_outputs(
        output_dir=base_dir / "dataset",
        manifest_path=base_dir / "manifest" / "appendix_validation_summary.json",
        dataset_manifest=dataset_manifest,
    )

    # legal_relation은 OpenSearch 전용 — 임베딩 여부와 무관하게 항상 import JSONL 최신화
    legal_relation_handoff_summary = export_legal_relation_handoff(
        dataset_dir=base_dir / "dataset",
        handoff_dir=base_dir / "handoff" / "qdrant_3collections",
    )

    embedding_summary = None
    if not args.skip_embed:
        emb_dir = base_dir / "emb" / "qdrant_3collections"
        handoff_dir = base_dir / "handoff" / "qdrant_3collections"
        cmd = [
            sys.executable,
            "scripts/embed_qdrant_3collections.py",
            "--dataset-dir",
            str(base_dir / "dataset"),
            "--emb-dir",
            str(emb_dir),
            "--handoff-dir",
            str(handoff_dir),
        ]
        if args.batch_size is not None:
            cmd.extend(["--batch-size", str(args.batch_size)])
        _run_subprocess(cmd)
        embedding_summary = {
            "handoff_dir": str(handoff_dir),
            "emb_dir": str(emb_dir),
        }
        if args.upload_dry_run:
            env = dict(os.environ)
            env["QDRANT_HANDOFF_DIR"] = str(handoff_dir)
            env["QDRANT_EMB_DIR"] = str(emb_dir)
            _run_subprocess([sys.executable, "scripts/upload/load_qdrant.py", "--dry-run"], env=env)

    summary = {
        "base_dir": str(base_dir),
        "expc_html_summary": expc_html_summary,
        "dataset_manifest": dataset_manifest,
        "appendix_validation_summary": appendix_validation_summary,
        "legal_relation_handoff_summary": legal_relation_handoff_summary,
        "embedding_summary": embedding_summary,
    }
    _write_json(base_dir / "manifest" / "rebuild_dataset_and_handoff_summary.json", summary)
    print("Dataset rebuild workflow finished")
    print(summary)


if __name__ == "__main__":
    main()
