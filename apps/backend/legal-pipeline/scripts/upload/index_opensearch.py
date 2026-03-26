from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from .config import COLLECTIONS, OPENSEARCH_URL
    from .opensearch_common import (
        build_index_payload,
        collection_index_name,
        create_index_if_missing,
        delete_index_if_exists,
    )
except ImportError:
    from config import COLLECTIONS, OPENSEARCH_URL
    from opensearch_common import (
        build_index_payload,
        collection_index_name,
        create_index_if_missing,
        delete_index_if_exists,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create OpenSearch indices for legal-pipeline collections")
    parser.add_argument("--collection", type=str, default=None, help="특정 컬렉션만 처리")
    parser.add_argument("--recreate", action="store_true", help="기존 인덱스 삭제 후 재생성")
    parser.add_argument("--dry-run", action="store_true", help="생성 payload만 출력하고 요청은 보내지 않음")
    args = parser.parse_args()

    targets = [args.collection] if args.collection else list(COLLECTIONS.keys())

    print("=" * 60)
    print("OpenSearch 인덱스 생성")
    print(f"  OPENSEARCH_URL: {OPENSEARCH_URL}")
    print("=" * 60)

    for collection_name in targets:
        if collection_name not in COLLECTIONS:
            raise ValueError(f"알 수 없는 컬렉션: {collection_name}")

        index_name = collection_index_name(collection_name)
        payload = build_index_payload(collection_name)
        print(f"\n▶ {collection_name} -> {index_name}")
        print(json.dumps({"index_name": index_name, "mapping_keys": sorted(payload["mappings"]["properties"].keys())}, ensure_ascii=False, indent=2))

        if args.dry_run:
            continue

        if args.recreate:
            delete_index_if_exists(index_name)
        create_index_if_missing(index_name, collection_name=collection_name)

    print("\n✅ OpenSearch 인덱스 처리 완료")


if __name__ == "__main__":
    main()
