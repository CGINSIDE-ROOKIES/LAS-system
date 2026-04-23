from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.embedding_backend import create_embedding_backend, load_embedding_settings
from src.common.io_utils import _iter_jsonl, _write_json, _write_jsonl
from scripts.embed_qdrant_3collections import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_COLLECTIONS,
    SUPPORTED_COLLECTIONS,
    embed_law_article,
    embed_simple_collection,
    _resolve_target_collections,
    write_embedding_manifest,
)


def _infer_collection_name(row: dict, *, relation_file: bool) -> str:
    if relation_file:
        return "legal_relation"
    return "law_article" if str(row.get("doc_type") or "").strip() == "law" else "legal_case"


def _load_patch_rows(dataset_patch_dir: Path) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    corpus_upserts = list(_iter_jsonl(dataset_patch_dir / "legal_corpus.upsert.jsonl"))
    corpus_deletes = list(_iter_jsonl(dataset_patch_dir / "legal_corpus.delete.jsonl"))
    relation_upserts = list(_iter_jsonl(dataset_patch_dir / "legal_relations.upsert.jsonl"))
    relation_deletes = list(_iter_jsonl(dataset_patch_dir / "legal_relations.delete.jsonl"))
    return corpus_upserts, corpus_deletes, relation_upserts, relation_deletes


def build_incremental_embeddings(
    *,
    dataset_patch_dir: Path,
    emb_dir: Path,
    handoff_dir: Path,
    delta_batch_id: str,
    batch_size: int,
    target_collections: tuple[str, ...] = DEFAULT_COLLECTIONS,
) -> dict:
    corpus_upserts, corpus_deletes, relation_upserts, relation_deletes = _load_patch_rows(dataset_patch_dir)
    delete_groups: dict[str, list[dict]] = defaultdict(list)
    embeddable_collections = set(target_collections)
    for row in corpus_deletes:
        collection_name = _infer_collection_name(row, relation_file=False)
        if collection_name in embeddable_collections:
            delete_groups[collection_name].append(row)
    for row in relation_deletes:
        if "legal_relation" in embeddable_collections:
            delete_groups["legal_relation"].append(row)

    corpus_embed_upserts = [
        row
        for row in corpus_upserts
        if _infer_collection_name(row, relation_file=False) in embeddable_collections
    ]
    relation_embed_upserts = list(relation_upserts) if "legal_relation" in embeddable_collections else []

    if not corpus_embed_upserts and not relation_embed_upserts:
        emb_dir.mkdir(parents=True, exist_ok=True)
        handoff_dir.mkdir(parents=True, exist_ok=True)
        collection_manifests = [
            {"collection_name": name, "count": 0, "skipped": True, "reason": "no patch rows"}
            for name in target_collections
        ]
        write_embedding_manifest(
            handoff_dir=handoff_dir,
            dataset_dir=dataset_patch_dir,
            emb_dir=emb_dir,
            collection_manifests=collection_manifests,
        )
        delete_manifest = {
            "delta_batch_id": delta_batch_id,
            "collections": {
                name: [
                    {
                        "id": row.get("id"),
                        "canonical_id": row.get("canonical_id"),
                        "_point_id": row.get("_point_id"),
                    }
                    for row in rows
                ]
                for name, rows in sorted(delete_groups.items())
            },
        }
        _write_json(handoff_dir / "delete_manifest.json", delete_manifest)
        manifest = {
            "delta_batch_id": delta_batch_id,
            "dataset_patch_dir": str(dataset_patch_dir),
            "emb_dir": str(emb_dir),
            "handoff_dir": str(handoff_dir),
            "corpus_upsert_count": 0,
            "relation_upsert_count": len(relation_upserts),
            "corpus_delete_count": len(corpus_deletes),
            "relation_delete_count": len(relation_deletes),
            "collections": collection_manifests,
        }
        _write_json(handoff_dir / "qdrant_incremental_manifest.json", manifest)
        return manifest

    with tempfile.TemporaryDirectory(prefix="incremental-dataset-") as tmp_dir:
        tmp_dataset_dir = Path(tmp_dir)
        _write_jsonl(tmp_dataset_dir / "legal_corpus.jsonl", corpus_embed_upserts)
        _write_jsonl(tmp_dataset_dir / "legal_relations.jsonl", relation_embed_upserts)

        model = create_embedding_backend(load_embedding_settings())
        collection_manifests: list[dict] = []

        try:
            if "law_article" in embeddable_collections and any(
                str(row.get("doc_type") or "").strip() == "law" for row in corpus_embed_upserts
            ):
                collection_manifests.append(
                    embed_law_article(
                        model=model,
                        dataset_dir=tmp_dataset_dir,
                        emb_dir=emb_dir,
                        handoff_dir=handoff_dir,
                        batch_size=batch_size,
                    )
                )
            elif "law_article" in embeddable_collections:
                collection_manifests.append(
                    {"collection_name": "law_article", "count": 0, "skipped": True, "reason": "no patch rows"}
                )
            for collection_name in target_collections:
                if collection_name == "law_article":
                    continue
                collection_manifests.append(
                    embed_simple_collection(
                        model=model,
                        dataset_dir=tmp_dataset_dir,
                        emb_dir=emb_dir,
                        handoff_dir=handoff_dir,
                        collection_name=collection_name,
                        batch_size=batch_size,
                    )
                )

            write_embedding_manifest(
                handoff_dir=handoff_dir,
                dataset_dir=tmp_dataset_dir,
                emb_dir=emb_dir,
                collection_manifests=collection_manifests,
            )
        finally:
            model.close()

    delete_manifest = {
        "delta_batch_id": delta_batch_id,
        "collections": {
            name: [
                {
                    "id": row.get("id"),
                    "canonical_id": row.get("canonical_id"),
                    "_point_id": row.get("_point_id"),
                }
                for row in rows
            ]
            for name, rows in sorted(delete_groups.items())
        },
    }
    _write_json(handoff_dir / "delete_manifest.json", delete_manifest)

    manifest = {
        "delta_batch_id": delta_batch_id,
        "dataset_patch_dir": str(dataset_patch_dir),
        "emb_dir": str(emb_dir),
        "handoff_dir": str(handoff_dir),
        "corpus_upsert_count": len(corpus_upserts),
        "relation_upsert_count": len(relation_upserts),
        "corpus_delete_count": len(corpus_deletes),
        "relation_delete_count": len(relation_deletes),
        "collections": collection_manifests,
    }
    _write_json(handoff_dir / "qdrant_incremental_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed incremental dataset patch for Qdrant handoff")
    parser.add_argument("--dataset-patch-dir", type=Path, required=True)
    parser.add_argument("--delta-batch-id", type=str, required=True)
    parser.add_argument("--emb-dir", type=Path, default=None)
    parser.add_argument("--handoff-dir", type=Path, default=None)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--collection",
        action="append",
        choices=SUPPORTED_COLLECTIONS,
        default=None,
        help="Target collection to embed. Repeat to select multiple. Default: law_article + legal_case",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    emb_dir = args.emb_dir or Path("data/emb/qdrant_incremental") / args.delta_batch_id
    handoff_dir = args.handoff_dir or Path("data/handoff/qdrant_incremental") / args.delta_batch_id
    target_collections = _resolve_target_collections(args.collection)

    manifest = build_incremental_embeddings(
        dataset_patch_dir=args.dataset_patch_dir,
        emb_dir=emb_dir,
        handoff_dir=handoff_dir,
        delta_batch_id=args.delta_batch_id,
        batch_size=args.batch_size,
        target_collections=target_collections,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
