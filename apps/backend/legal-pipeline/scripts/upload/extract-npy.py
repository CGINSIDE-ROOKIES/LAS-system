"""
scripts/upload/extract-npy.py

Rebuild .npy + meta.jsonl files from current Qdrant import JSONL handoff outputs.
This is optional because the main embedding pipeline already writes .npy files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from config import COLLECTIONS, DROP_FIELDS_ON_EXTRACT, EMB_DIR, HANDOFF_DIR, VECTOR_DIM


def _write_meta(meta_out: Path, meta_rows: list[dict]) -> None:
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    with meta_out.open("w", encoding="utf-8") as fout:
        for row in meta_rows:
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")


def _clean_meta_row(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in DROP_FIELDS_ON_EXTRACT}


def _validate_dim(arr: np.ndarray, label: str) -> None:
    if arr.ndim != 2:
        raise ValueError(f"{label} must be 2D: shape={arr.shape}")
    if arr.shape[1] != VECTOR_DIM:
        raise ValueError(f"{label} dim mismatch: expected {VECTOR_DIM}, got {arr.shape[1]}")


def extract_single(import_path: Path, npy_out: Path, meta_out: Path) -> None:
    vectors: list[list[float]] = []
    metas: list[dict] = []

    with import_path.open("r", encoding="utf-8") as fin:
        for idx, line in enumerate(fin, start=1):
            row = json.loads(line)
            vec = row.get("_vector")
            if vec is None:
                raise ValueError(f"line {idx}: _vector 필드 없음 — id={row.get('id')}")
            vectors.append(vec)
            metas.append(_clean_meta_row(row))

    arr = np.array(vectors, dtype=np.float32)
    _validate_dim(arr, npy_out.name)
    np.save(str(npy_out), arr)
    _write_meta(meta_out, metas)
    print(f"  완료: {len(metas)}건 / vector={arr.shape} / meta={meta_out}")


def extract_named(import_path: Path, body_out: Path, appendix_out: Path, meta_out: Path) -> None:
    body_vectors: list[list[float]] = []
    appendix_vectors: list[list[float]] = []
    metas: list[dict] = []

    with import_path.open("r", encoding="utf-8") as fin:
        for idx, line in enumerate(fin, start=1):
            row = json.loads(line)
            vectors = row.get("_vectors") or {}
            body = vectors.get("body")
            appendix = vectors.get("appendix")
            if body is None or appendix is None:
                raise ValueError(f"line {idx}: _vectors.body/_vectors.appendix 필드 없음 — id={row.get('id')}")
            body_vectors.append(body)
            appendix_vectors.append(appendix)
            metas.append(_clean_meta_row(row))

    body_arr = np.array(body_vectors, dtype=np.float32)
    appendix_arr = np.array(appendix_vectors, dtype=np.float32)
    _validate_dim(body_arr, body_out.name)
    _validate_dim(appendix_arr, appendix_out.name)
    np.save(str(body_out), body_arr)
    np.save(str(appendix_out), appendix_arr)
    _write_meta(meta_out, metas)
    print(
        f"  완료: {len(metas)}건 / body={body_arr.shape} / appendix={appendix_arr.shape} / meta={meta_out}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Qdrant import JSONL에서 .npy + meta.jsonl 재구성")
    parser.add_argument("--collection", type=str, default=None, help="특정 컬렉션만 재구성")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=EMB_DIR / "reconstructed",
        help="재구성 결과를 쓸 디렉터리",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.collection and args.collection not in COLLECTIONS:
        raise ValueError(f"알 수 없는 컬렉션: {args.collection}")

    targets = {args.collection: COLLECTIONS[args.collection]} if args.collection else COLLECTIONS

    print("=" * 60)
    print("Qdrant import JSONL -> .npy + meta.jsonl 재구성")
    print(f"  handoff_dir: {HANDOFF_DIR}")
    print(f"  out_dir: {out_dir}")
    print(f"  vector_dim: {VECTOR_DIM}")
    print("=" * 60)

    for name, info in targets.items():
        import_path = Path(info["payload_jsonl"])
        if not import_path.exists():
            print(f"\n[{name}] skip: import JSONL 없음 ({import_path})")
            continue

        print(f"\n▶ {name}")
        if info["vector_mode"] == "named":
            extract_named(
                import_path,
                out_dir / f"{name}.body.npy",
                out_dir / f"{name}.appendix.npy",
                out_dir / f"{name}.meta.jsonl",
            )
        else:
            extract_single(
                import_path,
                out_dir / f"{name}.npy",
                out_dir / f"{name}.meta.jsonl",
            )


if __name__ == "__main__":
    main()
