"""
scripts/upload/load_qdrant.py — current legal-pipeline handoff outputs to Qdrant.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid as _uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from config import (
    QDRANT_URL,
    QDRANT_API_KEY,
    QDRANT_TIMEOUT_SEC,
    EMB_DIR,
    HANDOFF_DIR,
    COLLECTIONS,
    BATCH_SIZE,
    COLLECTION_INTEGER_INDEX_FIELDS,
    COLLECTION_FLOAT_INDEX_FIELDS,
    VECTOR_DIM,
    EMBEDDING_MODEL,
)


def get_client() -> QdrantClient:
    return QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        timeout=QDRANT_TIMEOUT_SEC,
    )


def str_to_uuid(s: str) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, s))


def _normalize_integer_fields(row: dict, integer_fields: list[str]) -> dict:
    for field in integer_fields:
        val = row.get(field)
        if val is not None:
            try:
                row[field] = int(val)
            except (ValueError, TypeError):
                row[field] = None
    return row


def _normalize_float_fields(row: dict, float_fields: list[str]) -> dict:
    for field in float_fields:
        val = row.get(field)
        if val is not None:
            try:
                row[field] = float(val)
            except (ValueError, TypeError):
                row[field] = None
    return row


def _validate_vector_dim(vectors: np.ndarray, *, expected_dim: int, label: str) -> None:
    if vectors.ndim != 2:
        raise ValueError(f"{label} must be a 2D array: shape={vectors.shape}")
    if vectors.shape[1] != expected_dim:
        raise ValueError(f"{label} dim mismatch: expected {expected_dim}, got {vectors.shape[1]}")


def load_payload_rows(payload_path: Path, integer_fields: list[str], float_fields: list[str]) -> list[dict]:
    rows: list[dict] = []
    with open(payload_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row.pop("_vector", None)
            row.pop("_vectors", None)
            row.pop("_score", None)
            row = _normalize_integer_fields(row, integer_fields)
            row = _normalize_float_fields(row, float_fields)
            rows.append(row)
    return rows


def _validate_exists(path: Path, label: str):
    if not path.exists():
        raise FileNotFoundError(f"{label} 파일 없음: {path}")


def _load_single_payload_and_vectors(file_info: dict, integer_fields: list[str], float_fields: list[str]):
    npy_path = Path(file_info["npy"])
    payload_path = Path(file_info["payload_jsonl"])
    _validate_exists(npy_path, "NPY")
    _validate_exists(payload_path, "PAYLOAD")

    vectors = np.load(str(npy_path))
    _validate_vector_dim(vectors, expected_dim=VECTOR_DIM, label=str(npy_path.name))
    payloads = load_payload_rows(payload_path, integer_fields, float_fields)
    if len(vectors) != len(payloads):
        raise ValueError(f"vector / payload 개수 불일치: {len(vectors)} != {len(payloads)}")
    return vectors, payloads


def _load_named_payload_and_vectors(file_info: dict, integer_fields: list[str], float_fields: list[str]):
    body_path = Path(file_info["body_npy"])
    appendix_path = Path(file_info["appendix_npy"])
    payload_path = Path(file_info["payload_jsonl"])
    _validate_exists(body_path, "BODY NPY")
    _validate_exists(appendix_path, "APPENDIX NPY")
    _validate_exists(payload_path, "PAYLOAD")

    body_vectors = np.load(str(body_path))
    appendix_vectors = np.load(str(appendix_path))
    _validate_vector_dim(body_vectors, expected_dim=VECTOR_DIM, label=str(body_path.name))
    _validate_vector_dim(appendix_vectors, expected_dim=VECTOR_DIM, label=str(appendix_path.name))
    payloads = load_payload_rows(payload_path, integer_fields, float_fields)

    if not (len(body_vectors) == len(appendix_vectors) == len(payloads)):
        raise ValueError(
            f"body / appendix / payload 개수 불일치: {len(body_vectors)} / {len(appendix_vectors)} / {len(payloads)}"
        )
    return body_vectors, appendix_vectors, payloads


def _print_vector_summary(vectors: np.ndarray, label: str):
    norms = np.linalg.norm(vectors[: min(100, len(vectors))], axis=1)
    norm_ok = np.allclose(norms, 1.0, atol=1e-5)
    print(f"  {label}: {vectors.shape} / dtype={vectors.dtype} / 정규화={'✅ OK' if norm_ok else '⚠️ 비정규화'}")


def upsert_collection(
    client: QdrantClient,
    collection_name: str,
    file_info: dict,
    batch_size: int,
    dry_run: bool = False,
):
    integer_fields = COLLECTION_INTEGER_INDEX_FIELDS.get(collection_name, [])
    float_fields = COLLECTION_FLOAT_INDEX_FIELDS.get(collection_name, [])
    vector_mode = file_info["vector_mode"]

    if vector_mode == "named":
        body_vectors, appendix_vectors, payloads = _load_named_payload_and_vectors(
            file_info,
            integer_fields,
            float_fields,
        )
        _print_vector_summary(body_vectors, "body")
        _print_vector_summary(appendix_vectors, "appendix")

        if dry_run:
            print(f"  🔍 dry-run 모드 — 적재 생략 ({len(payloads)}건)")
            return

        total = len(payloads)
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            points = []
            for i in range(start, end):
                pid = payloads[i].get("_point_id") or payloads[i].get("id")
                if not pid:
                    raise ValueError(f"point id 없음 at row {i}")
                points.append(
                    PointStruct(
                        id=str_to_uuid(str(pid)),
                        vector={
                            "body": body_vectors[i].tolist(),
                            "appendix": appendix_vectors[i].tolist(),
                        },
                        payload=payloads[i],
                    )
                )
            client.upsert(collection_name=collection_name, points=points)
            print(f"  업서트: {start:,} ~ {end:,} / {total:,}")
        return

    vectors, payloads = _load_single_payload_and_vectors(file_info, integer_fields, float_fields)
    _print_vector_summary(vectors, "vector")

    if dry_run:
        print(f"  🔍 dry-run 모드 — 적재 생략 ({len(payloads)}건)")
        return

    total = len(payloads)
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        points = []
        for i in range(start, end):
            pid = payloads[i].get("_point_id") or payloads[i].get("id")
            if not pid:
                raise ValueError(f"point id 없음 at row {i}")
            points.append(
                PointStruct(
                    id=str_to_uuid(str(pid)),
                    vector=vectors[i].tolist(),
                    payload=payloads[i],
                )
            )
        client.upsert(collection_name=collection_name, points=points)
        print(f"  업서트: {start:,} ~ {end:,} / {total:,}")


def main():
    parser = argparse.ArgumentParser(description="NPY + import JSONL을 Qdrant에 적재")
    parser.add_argument("--dry-run", action="store_true", help="파일 검증만 하고 업서트는 하지 않음")
    parser.add_argument("--collection", type=str, default=None, help="특정 컬렉션만 적재")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help=f"배치 크기 (기본: {BATCH_SIZE})")
    args = parser.parse_args()

    if args.collection and args.collection not in COLLECTIONS:
        raise ValueError(f"알 수 없는 컬렉션: {args.collection}")
    targets = {args.collection: COLLECTIONS[args.collection]} if args.collection else COLLECTIONS
    client = get_client()

    print("=" * 60)
    print("Qdrant 적재")
    print(f"  dry_run: {args.dry_run}")
    print(f"  QDRANT_URL: {QDRANT_URL}")
    print(f"  embedding_model: {EMBEDDING_MODEL}")
    print(f"  vector_dim: {VECTOR_DIM}")
    print(f"  emb_dir: {EMB_DIR}")
    print(f"  handoff_dir: {HANDOFF_DIR}")
    print("=" * 60)

    for col_name, file_info in targets.items():
        print(f"\n▶ {col_name}")
        print(json.dumps({k: str(v) for k, v in file_info.items()}, ensure_ascii=False, indent=2))
        upsert_collection(
            client,
            col_name,
            file_info,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )

    print("\n✅ 전체 적재 완료")


if __name__ == "__main__":
    main()
