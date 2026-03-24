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

from sentence_transformers import SentenceTransformer

from src.common.io_utils import _iter_jsonl, _write_json, _write_jsonl
from scripts.embed_qdrant_3collections import (
    DEFAULT_BATCH_SIZE,
    MODEL_NAME,
    embed_law_article,
    embed_simple_collection,
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
) -> dict:
    corpus_upserts, corpus_deletes, relation_upserts, relation_deletes = _load_patch_rows(dataset_patch_dir)
    delete_groups: dict[str, list[dict]] = defaultdict(list)
    for row in corpus_deletes:
        delete_groups[_infer_collection_name(row, relation_file=False)].append(row)
    for row in relation_deletes:
        delete_groups[_infer_collection_name(row, relation_file=True)].append(row)

    if not corpus_upserts and not relation_upserts:
        emb_dir.mkdir(parents=True, exist_ok=True)
        handoff_dir.mkdir(parents=True, exist_ok=True)
        collection_manifests = [
            {"collection_name": "law_article", "count": 0, "skipped": True, "reason": "no patch rows"},
            {"collection_name": "legal_case", "count": 0, "skipped": True, "reason": "no patch rows"},
            {"collection_name": "legal_relation", "count": 0, "skipped": True, "reason": "no patch rows"},
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
            "relation_upsert_count": 0,
            "corpus_delete_count": len(corpus_deletes),
            "relation_delete_count": len(relation_deletes),
            "collections": collection_manifests,
        }
        _write_json(handoff_dir / "qdrant_incremental_manifest.json", manifest)
        return manifest

    with tempfile.TemporaryDirectory(prefix="incremental-dataset-") as tmp_dir:
        tmp_dataset_dir = Path(tmp_dir)
        _write_jsonl(tmp_dataset_dir / "legal_corpus.jsonl", corpus_upserts)
        _write_jsonl(tmp_dataset_dir / "legal_relations.jsonl", relation_upserts)

        model = SentenceTransformer(MODEL_NAME)
        collection_manifests: list[dict] = []

        if any(str(row.get("doc_type") or "").strip() == "law" for row in corpus_upserts):
            collection_manifests.append(
                embed_law_article(
                    model=model,
                    dataset_dir=tmp_dataset_dir,
                    emb_dir=emb_dir,
                    handoff_dir=handoff_dir,
                    batch_size=batch_size,
                )
            )
        else:
            collection_manifests.append({"collection_name": "law_article", "count": 0, "skipped": True, "reason": "no patch rows"})
        for collection_name in ("legal_case", "legal_relation"):
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    emb_dir = args.emb_dir or Path("data/emb/qdrant_incremental") / args.delta_batch_id
    handoff_dir = args.handoff_dir or Path("data/handoff/qdrant_incremental") / args.delta_batch_id

    manifest = build_incremental_embeddings(
        dataset_patch_dir=args.dataset_patch_dir,
        emb_dir=emb_dir,
        handoff_dir=handoff_dir,
        delta_batch_id=args.delta_batch_id,
        batch_size=args.batch_size,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
