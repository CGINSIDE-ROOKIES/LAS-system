from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from sentence_transformers import SentenceTransformer


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
EMBEDDING_PASSAGE_PREFIX = ""
NORMALIZE_EMBEDDINGS = True
EMBEDDING_DTYPE = "float32"
DEFAULT_BATCH_SIZE = 32


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _stable_law_level(row: dict) -> str | None:
    value = row.get("law_level") or row.get("classified_level")
    if value in (None, ""):
        return None
    return str(value).strip()


def _point_id_from_row(row: dict) -> str:
    value = row.get("id")
    if value in (None, ""):
        raise ValueError("row.id is required to build _point_id")
    return str(value)


def _assert_unique_ids(rows: Sequence[dict], *, variant: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []

    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            raise ValueError(f"[{variant}] empty id found")
        if row_id in seen:
            duplicates.append(row_id)
        seen.add(row_id)

    if duplicates:
        sample = duplicates[:10]
        raise ValueError(
            f"[{variant}] duplicate ids found: count={len(duplicates)}, sample={sample}"
        )


def _load_variant_rows(dataset_dir: Path, variant: str) -> list[dict]:
    body_path = dataset_dir / "legal_corpus.jsonl"
    appendix_clean_path = dataset_dir / "legal_appendix_clean.jsonl"
    appendix_table_path = dataset_dir / "legal_appendix_table.jsonl"
    relation_path = dataset_dir / "legal_relations.jsonl"

    body_rows = read_jsonl(body_path) if body_path.exists() else []
    appendix_clean_rows = read_jsonl(appendix_clean_path) if appendix_clean_path.exists() else []
    appendix_table_rows = read_jsonl(appendix_table_path) if appendix_table_path.exists() else []
    relation_rows = read_jsonl(relation_path) if relation_path.exists() else []

    if variant == "body_only":
        rows = body_rows
    elif variant == "body_plus_annex":
        rows = body_rows + appendix_clean_rows + appendix_table_rows
    elif variant == "body_annex_related":
        rows = body_rows + appendix_clean_rows + appendix_table_rows + relation_rows
    else:
        raise ValueError(f"Unsupported variant: {variant}")

    return rows


def build_variant(
    dataset_dir: Path,
    variant: str,
) -> tuple[list[dict], list[str], list[dict]]:
    rows = _load_variant_rows(dataset_dir, variant)
    _assert_unique_ids(rows, variant=variant)

    texts: list[str] = []
    metas: list[dict] = []
    source_rows: list[dict] = []

    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue

        source_row = dict(row)
        source_rows.append(source_row)

        meta = {
            "id": row.get("id"),
            "doc_type": row.get("doc_type"),
            "doc_type_label": row.get("doc_type_label"),
            "law_name": row.get("law_name"),
            "law_id": row.get("law_id"),
            "mst": row.get("mst"),
            "ef_yd": row.get("ef_yd"),
            "kind_name": row.get("kind_name"),
            "classified_level": row.get("classified_level"),
            "law_level": _stable_law_level(row),
            "source_group": row.get("source_group"),
            "part_type": row.get("part_type"),
            "section_type": row.get("section_type"),
            "article_no": row.get("article_no"),
            "article_no_display": row.get("article_no_display"),
            "article_key": row.get("article_key"),
            "appendix_title": row.get("appendix_title"),
            "root_law_name": row.get("root_law_name"),
            "related_law_name": row.get("related_law_name"),
            "relation_types": row.get("relation_types"),
            "source_file_path": row.get("source_file_path"),
            "chunk_index": row.get("chunk_index"),
            "text_len": len(text),
        }

        metas.append(meta)
        texts.append(text)

    return metas, texts, source_rows


def _build_import_rows(
    metas: Sequence[dict],
    texts: Sequence[str],
    embeddings: np.ndarray,
) -> list[dict]:
    rows: list[dict] = []

    for meta, text, vector in zip(metas, texts, embeddings, strict=True):
        row = dict(meta)
        row["text"] = text
        row["_point_id"] = _point_id_from_row(meta)
        row["_vector"] = vector.astype(np.float32).tolist()
        row["_score"] = None
        row["embedding_model"] = MODEL_NAME
        row["embedding_passage_prefix"] = EMBEDDING_PASSAGE_PREFIX
        row["normalized"] = NORMALIZE_EMBEDDINGS
        rows.append(row)

    return rows


def _write_variant_source(handoff_dir: Path, variant: str, source_rows: Sequence[dict]) -> Path:
    source_dir = handoff_dir / "source"
    source_path = source_dir / f"{variant}.jsonl"
    write_jsonl(source_path, source_rows)
    return source_path


def _write_variant_import(handoff_dir: Path, variant: str, import_rows: Sequence[dict]) -> Path:
    import_dir = handoff_dir / "import"
    import_path = import_dir / f"{variant}_for_import.jsonl"
    write_jsonl(import_path, import_rows)
    return import_path


def embed_variant(
    model: SentenceTransformer,
    dataset_dir: Path,
    emb_dir: Path,
    handoff_dir: Path,
    variant: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict:
    metas, texts, source_rows = build_variant(dataset_dir, variant)

    if not texts:
        raise ValueError(f"[{variant}] no texts found to embed")

    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=NORMALIZE_EMBEDDINGS,
        precision=EMBEDDING_DTYPE,
    )

    embeddings = embeddings.astype(np.float32)

    emb_dir.mkdir(parents=True, exist_ok=True)
    npy_path = emb_dir / f"{variant}.npy"
    meta_path = emb_dir / f"{variant}.meta.jsonl"
    variant_manifest_path = emb_dir / f"{variant}.manifest.json"

    np.save(npy_path, embeddings)
    write_jsonl(meta_path, metas)

    import_rows = _build_import_rows(metas, texts, embeddings)
    source_path = _write_variant_source(handoff_dir, variant, source_rows)
    import_path = _write_variant_import(handoff_dir, variant, import_rows)

    variant_manifest = {
        "variant": variant,
        "model_name": MODEL_NAME,
        "count": len(metas),
        "embedding_dim": int(embeddings.shape[1]) if len(embeddings) else 0,
        "normalized": NORMALIZE_EMBEDDINGS,
        "dtype": "float32",
        "batch_size": batch_size,
        "dataset_dir": str(dataset_dir),
        "npy_path": str(npy_path),
        "meta_path": str(meta_path),
        "source_jsonl_path": str(source_path),
        "import_jsonl_path": str(import_path),
    }
    with variant_manifest_path.open("w", encoding="utf-8") as f:
        json.dump(variant_manifest, f, ensure_ascii=False, indent=2)

    return variant_manifest


def _resolve_variants(dataset_dir: Path) -> list[str]:
    variants = ["body_only", "body_plus_annex"]

    relation_path = dataset_dir / "legal_relations.jsonl"
    if relation_path.exists():
        relation_rows = read_jsonl(relation_path)
        if relation_rows:
            variants.append("body_annex_related")

    return variants


def write_embedding_manifest(
    handoff_dir: Path,
    dataset_dir: Path,
    emb_dir: Path,
    variant_manifests: Sequence[dict],
) -> Path:
    manifest_path = handoff_dir / "embedding_manifest.json"
    payload = {
        "model_name": MODEL_NAME,
        "embedding_dim": 768,
        "normalized": NORMALIZE_EMBEDDINGS,
        "dtype": "float32",
        "metric": "cosine",
        "embedding_passage_prefix": EMBEDDING_PASSAGE_PREFIX,
        "dataset_dir": str(dataset_dir),
        "emb_dir": str(emb_dir),
        "variants": list(variant_manifests),
    }
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed handoff variants and write import-ready JSONL files.")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("data/run/c/dataset"),
        help="Dataset directory containing legal_corpus.jsonl and appendix datasets.",
    )
    parser.add_argument(
        "--emb-dir",
        type=Path,
        default=Path("data/run/c/emb"),
        help="Directory to write .npy and meta outputs.",
    )
    parser.add_argument(
        "--handoff-dir",
        type=Path,
        default=Path("data/run/c/handoff"),
        help="Directory to write source/import JSONL and embedding manifest.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="SentenceTransformer encode batch size.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    dataset_dir: Path = args.dataset_dir
    emb_dir: Path = args.emb_dir
    handoff_dir: Path = args.handoff_dir
    batch_size: int = args.batch_size

    if not dataset_dir.exists():
        raise FileNotFoundError(f"dataset_dir not found: {dataset_dir}")

    model = SentenceTransformer(MODEL_NAME)

    variant_manifests: list[dict] = []
    for variant in _resolve_variants(dataset_dir):
        manifest = embed_variant(
            model=model,
            dataset_dir=dataset_dir,
            emb_dir=emb_dir,
            handoff_dir=handoff_dir,
            variant=variant,
            batch_size=batch_size,
        )
        variant_manifests.append(manifest)

    write_embedding_manifest(
        handoff_dir=handoff_dir,
        dataset_dir=dataset_dir,
        emb_dir=emb_dir,
        variant_manifests=variant_manifests,
    )


if __name__ == "__main__":
    main()