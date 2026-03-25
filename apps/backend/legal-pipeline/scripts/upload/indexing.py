"""
scripts/upload/indexing.py — create Qdrant collections for current legal-pipeline outputs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams,
    Distance,
    PayloadSchemaType,
    HnswConfigDiff,
    OptimizersConfigDiff,
)

from config import (
    QDRANT_URL,
    QDRANT_API_KEY,
    QDRANT_TIMEOUT_SEC,
    COLLECTIONS,
    VECTOR_DIM,
    EMBEDDING_MODEL,
    HNSW_M,
    HNSW_EF_CONSTRUCT,
    INDEXING_THRESHOLD,
    COLLECTION_KEYWORD_INDEX_FIELDS,
    COLLECTION_INTEGER_INDEX_FIELDS,
    COLLECTION_FLOAT_INDEX_FIELDS,
)


def get_client() -> QdrantClient:
    return QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        timeout=QDRANT_TIMEOUT_SEC,
    )


def _build_vectors_config(name: str, config: dict):
    if config["vector_mode"] == "named":
        return {
            "body": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            "appendix": VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        }
    return VectorParams(size=VECTOR_DIM, distance=Distance.COSINE)


def create_collection(client: QdrantClient, name: str, config: dict, recreate: bool = False):
    existing = [c.name for c in client.get_collections().collections]

    if name in existing:
        if recreate:
            print(f"  기존 컬렉션 삭제: {name}")
            client.delete_collection(collection_name=name)
        else:
            print(f"  이미 존재 — 스킵: {name}")
            return False

    client.create_collection(
        collection_name=name,
        vectors_config=_build_vectors_config(name, config),
        hnsw_config=HnswConfigDiff(m=HNSW_M, ef_construct=HNSW_EF_CONSTRUCT),
        optimizers_config=OptimizersConfigDiff(indexing_threshold=INDEXING_THRESHOLD),
    )
    print(f"  컬렉션 생성 완료: {name}")
    return True


def create_payload_indexes(client: QdrantClient, name: str):
    keyword_fields = COLLECTION_KEYWORD_INDEX_FIELDS.get(name, [])
    integer_fields = COLLECTION_INTEGER_INDEX_FIELDS.get(name, [])
    float_fields = COLLECTION_FLOAT_INDEX_FIELDS.get(name, [])

    for field in keyword_fields:
        client.create_payload_index(
            collection_name=name,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
    print(f"    KEYWORD 인덱스 {len(keyword_fields)}개 생성")

    for field in integer_fields:
        client.create_payload_index(
            collection_name=name,
            field_name=field,
            field_schema=PayloadSchemaType.INTEGER,
        )
    print(f"    INTEGER 인덱스 {len(integer_fields)}개 생성")

    for field in float_fields:
        client.create_payload_index(
            collection_name=name,
            field_name=field,
            field_schema=PayloadSchemaType.FLOAT,
        )
    print(f"    FLOAT 인덱스 {len(float_fields)}개 생성")


def verify_collection(client: QdrantClient, name: str):
    info = client.get_collection(collection_name=name)
    vectors = info.config.params.vectors

    print(f"\n  [{name}] 검증")
    print(f"    포인트 수:  {info.points_count}")
    if hasattr(vectors, "size"):
        print(f"    벡터 차원:  {vectors.size}")
        print(f"    거리 함수:  {vectors.distance}")
    else:
        try:
            names = list(vectors.keys())
        except Exception:
            names = []
        print(f"    named vectors: {names}")
    print(f"    상태:       {info.status}")


def main():
    parser = argparse.ArgumentParser(description="Qdrant 컬렉션 생성 및 인덱싱")
    parser.add_argument("--recreate", action="store_true", help="기존 컬렉션 삭제 후 재생성")
    parser.add_argument("--collection", type=str, default=None, help="특정 컬렉션만 처리")
    args = parser.parse_args()

    client = get_client()
    targets = [args.collection] if args.collection else list(COLLECTIONS.keys())

    print("=" * 60)
    print("Qdrant 컬렉션 생성 + 인덱싱")
    print(f"  QDRANT_URL: {QDRANT_URL}")
    print(f"  embedding_model: {EMBEDDING_MODEL}")
    print(f"  vector_dim: {VECTOR_DIM}")
    print("=" * 60)

    for col_name in targets:
        if col_name not in COLLECTIONS:
            print(f"  알 수 없는 컬렉션: {col_name}")
            sys.exit(1)

        print(f"\n▶ {col_name}")
        created = create_collection(client, col_name, COLLECTIONS[col_name], recreate=args.recreate)
        if created or args.recreate:
            create_payload_indexes(client, col_name)
        verify_collection(client, col_name)

    print("\n✅ 인덱싱 완료")


if __name__ == "__main__":
    main()
