from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qdrant_client.models import PointIdsList

from scripts.upload.load_qdrant import get_client, str_to_uuid, upsert_collection


def _load_manifest(patch_dir: Path) -> dict:
    manifest_path = patch_dir / "qdrant_incremental_manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _delete_points(client, collection_name: str, items: list[dict], dry_run: bool) -> None:
    point_ids = [
        str_to_uuid(str(item.get("_point_id")))
        for item in items
        if str(item.get("_point_id") or "").strip()
    ]
    if not point_ids:
        return
    if dry_run:
        print(f"  dry-run delete: {collection_name} / {len(point_ids)}건")
        return
    client.delete(collection_name=collection_name, points_selector=PointIdsList(points=point_ids))
    print(f"  delete: {collection_name} / {len(point_ids)}건")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply incremental Qdrant patch")
    parser.add_argument("--patch-dir", type=Path, required=True, help="handoff incremental patch directory")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--collection", action="append", default=None, help="특정 컬렉션만 적용. 반복 지정 가능")
    args = parser.parse_args()

    patch_dir = args.patch_dir
    manifest = _load_manifest(patch_dir)
    delete_manifest = json.loads((patch_dir / "delete_manifest.json").read_text(encoding="utf-8"))
    client = None if args.dry_run else get_client()
    selected_collections = set(args.collection or [])

    print("=" * 60)
    print("Qdrant incremental patch")
    print(f"  patch_dir: {patch_dir}")
    print(f"  dry_run: {args.dry_run}")
    if selected_collections:
        print(f"  collections: {', '.join(sorted(selected_collections))}")
    print("=" * 60)

    for collection_name, items in sorted(delete_manifest.get("collections", {}).items()):
        if selected_collections and collection_name not in selected_collections:
            continue
        _delete_points(client, collection_name, items, args.dry_run)

    for collection in manifest.get("collections", []):
        collection_name = str(collection.get("collection_name") or "").strip()
        if not collection_name:
            continue
        if selected_collections and collection_name not in selected_collections:
            continue
        if collection.get("skipped"):
            print(f"  skip upsert: {collection_name}")
            continue

        file_info: dict[str, object]
        vector_names = collection.get("vector_names") or []
        if vector_names == ["body", "appendix"]:
            file_info = {
                "vector_mode": "named",
                "body_npy": collection.get("body_npy_path"),
                "appendix_npy": collection.get("appendix_npy_path"),
                "payload_jsonl": collection.get("import_jsonl_path"),
            }
        else:
            file_info = {
                "vector_mode": "single",
                "npy": collection.get("npy_path"),
                "payload_jsonl": collection.get("import_jsonl_path"),
            }
        print(f"\n▶ patch upsert: {collection_name}")
        upsert_collection(
            client=client,
            collection_name=collection_name,
            file_info=file_info,
            batch_size=500,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
