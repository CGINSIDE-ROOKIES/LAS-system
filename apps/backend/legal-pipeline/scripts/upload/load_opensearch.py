from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.io_utils import _write_json

try:
    from .config import COLLECTIONS, OPENSEARCH_BULK_DIR, OPENSEARCH_URL
    from .opensearch_common import (
        batched,
        build_upsert_ndjson,
        bulk_request,
        collection_index_name,
        create_index_if_missing,
        default_batch_size,
        delete_index_if_exists,
        iter_jsonl,
        summarize_bulk_result,
    )
except ImportError:
    from config import COLLECTIONS, OPENSEARCH_BULK_DIR, OPENSEARCH_URL
    from opensearch_common import (
        batched,
        build_upsert_ndjson,
        bulk_request,
        collection_index_name,
        create_index_if_missing,
        default_batch_size,
        delete_index_if_exists,
        iter_jsonl,
        summarize_bulk_result,
    )


def _validate_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} 파일 없음: {path}")


def load_collection_rows(collection_name: str) -> list[dict]:
    payload_path = Path(COLLECTIONS[collection_name]["payload_jsonl"])
    _validate_exists(payload_path, "OpenSearch payload JSONL")
    return list(iter_jsonl(payload_path))


def write_bulk_file(
    *,
    collection_name: str,
    rows: list[dict],
    output_dir: Path,
) -> tuple[Path, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{collection_name}.bulk.ndjson"
    index_name = collection_index_name(collection_name)
    body, count = build_upsert_ndjson(rows, collection_name=collection_name, index_name=index_name)
    output_path.write_text(body, encoding="utf-8")
    return output_path, count


def upload_collection(
    *,
    collection_name: str,
    rows: list[dict],
    batch_size: int,
    create_index: bool,
    recreate_index: bool,
) -> dict:
    index_name = collection_index_name(collection_name)
    if recreate_index:
        delete_index_if_exists(index_name)
    if create_index:
        create_index_if_missing(index_name, collection_name=collection_name)

    success_count = 0
    failure_count = 0
    failures: list[dict] = []
    for batch in batched(rows, batch_size):
        payload = bulk_request(
            build_upsert_ndjson(batch, collection_name=collection_name, index_name=index_name)[0]
        )
        summary = summarize_bulk_result(payload)
        success_count += summary["success_count"]
        failure_count += summary["failure_count"]
        failures.extend(summary["failures"])

    return {
        "index_name": index_name,
        "success_count": success_count,
        "failure_count": failure_count,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load legal-pipeline handoff payloads into OpenSearch")
    parser.add_argument("--collection", type=str, default=None, help="특정 컬렉션만 처리")
    parser.add_argument("--batch-size", type=int, default=default_batch_size())
    parser.add_argument("--dry-run", action="store_true", help="bulk 파일만 만들고 업로드는 생략")
    parser.add_argument("--no-create-index", action="store_true", help="인덱스 자동 생성 비활성화")
    parser.add_argument("--recreate-index", action="store_true", help="기존 인덱스 삭제 후 재생성")
    parser.add_argument("--output-dir", type=Path, default=OPENSEARCH_BULK_DIR)
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be > 0")

    targets = [args.collection] if args.collection else list(COLLECTIONS.keys())
    manifest = {
        "opensearch_url": OPENSEARCH_URL,
        "output_dir": str(args.output_dir),
        "dry_run": args.dry_run,
        "collections": [],
    }

    print("=" * 60)
    print("OpenSearch 전체 적재")
    print(f"  OPENSEARCH_URL: {OPENSEARCH_URL}")
    print(f"  output_dir: {args.output_dir}")
    print(f"  dry_run: {args.dry_run}")
    print("=" * 60)

    for collection_name in targets:
        if collection_name not in COLLECTIONS:
            raise ValueError(f"알 수 없는 컬렉션: {collection_name}")

        rows = load_collection_rows(collection_name)
        bulk_path, row_count = write_bulk_file(
            collection_name=collection_name,
            rows=rows,
            output_dir=args.output_dir,
        )
        entry = {
            "collection_name": collection_name,
            "index_name": collection_index_name(collection_name),
            "payload_jsonl_path": str(COLLECTIONS[collection_name]["payload_jsonl"]),
            "bulk_ndjson_path": str(bulk_path),
            "row_count": row_count,
        }
        print(f"\n▶ {collection_name}: rows={row_count} bulk={bulk_path}")

        if args.dry_run:
            entry["skipped"] = True
            entry["reason"] = "dry_run"
        else:
            entry.update(
                upload_collection(
                    collection_name=collection_name,
                    rows=rows,
                    batch_size=args.batch_size,
                    create_index=not args.no_create_index,
                    recreate_index=args.recreate_index,
                )
            )
            print(
                "  uploaded:"
                f" success={entry['success_count']}"
                f" failure={entry['failure_count']}"
            )

        manifest["collections"].append(entry)

    _write_json(args.output_dir / "opensearch_bulk_manifest.json", manifest)
    print("\n✅ OpenSearch 전체 적재 완료")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
