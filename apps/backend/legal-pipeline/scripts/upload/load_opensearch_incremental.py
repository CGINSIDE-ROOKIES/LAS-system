from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.io_utils import _iter_jsonl, _write_json

try:
    from .config import OPENSEARCH_INCREMENTAL_DIR, OPENSEARCH_URL
    from .opensearch_common import (
        build_delete_ndjson,
        build_upsert_ndjson,
        bulk_request,
        collection_index_name,
        create_index_if_missing,
        summarize_bulk_result,
    )
except ImportError:
    from config import OPENSEARCH_INCREMENTAL_DIR, OPENSEARCH_URL
    from opensearch_common import (
        build_delete_ndjson,
        build_upsert_ndjson,
        bulk_request,
        collection_index_name,
        create_index_if_missing,
        summarize_bulk_result,
    )


def _infer_collection_name(row: dict, *, relation_file: bool) -> str:
    collection_name = str(row.get("collection_name") or "").strip()
    if collection_name:
        return collection_name
    if relation_file:
        return "legal_relation"
    return "law_article" if str(row.get("doc_type") or "").strip() == "law" else "legal_case"


def _load_delta_batch_id(dataset_patch_dir: Path) -> str:
    manifest_path = dataset_patch_dir / "delta_manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        delta_batch_id = str(payload.get("delta_batch_id") or "").strip()
        if delta_batch_id:
            return delta_batch_id
    return dataset_patch_dir.name


def _load_patch_groups(dataset_patch_dir: Path) -> tuple[dict[str, list[dict]], dict[str, list[dict]], str]:
    delta_batch_id = _load_delta_batch_id(dataset_patch_dir)
    upserts: dict[str, list[dict]] = defaultdict(list)
    deletes: dict[str, list[dict]] = defaultdict(list)

    for row in _iter_jsonl(dataset_patch_dir / "legal_corpus.upsert.jsonl"):
        upserts[_infer_collection_name(row, relation_file=False)].append(row)
    for row in _iter_jsonl(dataset_patch_dir / "legal_relations.upsert.jsonl"):
        upserts[_infer_collection_name(row, relation_file=True)].append(row)
    for row in _iter_jsonl(dataset_patch_dir / "legal_corpus.delete.jsonl"):
        deletes[_infer_collection_name(row, relation_file=False)].append(row)
    for row in _iter_jsonl(dataset_patch_dir / "legal_relations.delete.jsonl"):
        deletes[_infer_collection_name(row, relation_file=True)].append(row)

    return dict(upserts), dict(deletes), delta_batch_id


def build_incremental_bulk_files(
    *,
    dataset_patch_dir: Path,
    output_dir: Path,
) -> dict:
    upserts, deletes, delta_batch_id = _load_patch_groups(dataset_patch_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    collections = sorted(set(upserts) | set(deletes))
    manifest = {
        "delta_batch_id": delta_batch_id,
        "dataset_patch_dir": str(dataset_patch_dir),
        "output_dir": str(output_dir),
        "collections": [],
    }

    for collection_name in collections:
        index_name = collection_index_name(collection_name)
        upsert_body, upsert_count = build_upsert_ndjson(
            upserts.get(collection_name, []),
            collection_name=collection_name,
            index_name=index_name,
        )
        delete_body, delete_count = build_delete_ndjson(
            deletes.get(collection_name, []),
            index_name=index_name,
        )

        upsert_path = output_dir / f"{collection_name}.upsert.ndjson"
        delete_path = output_dir / f"{collection_name}.delete.ndjson"
        upsert_path.write_text(upsert_body, encoding="utf-8")
        delete_path.write_text(delete_body, encoding="utf-8")

        manifest["collections"].append(
            {
                "collection_name": collection_name,
                "index_name": index_name,
                "upsert_count": upsert_count,
                "delete_count": delete_count,
                "upsert_ndjson_path": str(upsert_path),
                "delete_ndjson_path": str(delete_path),
            }
        )

    _write_json(output_dir / "opensearch_incremental_manifest.json", manifest)
    return manifest


def apply_incremental_bulk(manifest: dict, *, create_index: bool) -> dict:
    updated_manifest = dict(manifest)
    updated_collections: list[dict] = []

    for collection in manifest.get("collections", []):
        entry = dict(collection)
        collection_name = str(entry["collection_name"])
        if create_index:
            create_index_if_missing(entry["index_name"], collection_name=collection_name)

        delete_body = Path(entry["delete_ndjson_path"]).read_text(encoding="utf-8")
        if delete_body.strip():
            delete_summary = summarize_bulk_result(bulk_request(delete_body))
        else:
            delete_summary = {"success_count": 0, "failure_count": 0, "failures": [], "errors": False}

        upsert_body = Path(entry["upsert_ndjson_path"]).read_text(encoding="utf-8")
        if upsert_body.strip():
            upsert_summary = summarize_bulk_result(bulk_request(upsert_body))
        else:
            upsert_summary = {"success_count": 0, "failure_count": 0, "failures": [], "errors": False}

        entry["delete_result"] = delete_summary
        entry["upsert_result"] = upsert_summary
        updated_collections.append(entry)

    updated_manifest["collections"] = updated_collections
    return updated_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply incremental OpenSearch patch")
    parser.add_argument("--dataset-patch-dir", type=Path, required=True, help="dataset patch directory")
    parser.add_argument("--output-dir", type=Path, default=None, help="incremental NDJSON output directory")
    parser.add_argument("--dry-run", action="store_true", help="patch 파일만 만들고 업로드는 생략")
    parser.add_argument("--no-create-index", action="store_true", help="인덱스 자동 생성 비활성화")
    args = parser.parse_args()

    delta_batch_id = _load_delta_batch_id(args.dataset_patch_dir)
    output_dir = args.output_dir or (OPENSEARCH_INCREMENTAL_DIR / delta_batch_id)
    manifest = build_incremental_bulk_files(
        dataset_patch_dir=args.dataset_patch_dir,
        output_dir=output_dir,
    )

    print("=" * 60)
    print("OpenSearch incremental patch")
    print(f"  OPENSEARCH_URL: {OPENSEARCH_URL}")
    print(f"  dataset_patch_dir: {args.dataset_patch_dir}")
    print(f"  output_dir: {output_dir}")
    print(f"  dry_run: {args.dry_run}")
    print("=" * 60)

    if args.dry_run:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return

    uploaded_manifest = apply_incremental_bulk(
        manifest,
        create_index=not args.no_create_index,
    )
    _write_json(output_dir / "opensearch_incremental_manifest.json", uploaded_manifest)
    print(json.dumps(uploaded_manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
