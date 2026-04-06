from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.embedding_backend import create_embedding_backend, load_embedding_settings
from src.export.qdrant_point_id import (
    build_qdrant_point_id,
    canonical_id_from_row,
)


EMBEDDING_SETTINGS = load_embedding_settings()
MODEL_NAME = EMBEDDING_SETTINGS.model_name
EMBEDDING_PROVIDER = EMBEDDING_SETTINGS.provider
EMBEDDING_PASSAGE_PREFIX = ""
NORMALIZE_EMBEDDINGS = EMBEDDING_SETTINGS.normalize_embeddings
EMBEDDING_DTYPE = EMBEDDING_SETTINGS.dtype
DEFAULT_BATCH_SIZE = 128
CASE_DOC_TYPES = {"prec", "detc", "decc", "expc"}
COLLECTIONS = ("law_article", "legal_case")
APPENDIX_VECTOR_PLACEHOLDER = "[NO_APPENDIX_LINKED]"
LAW_ARTICLE_VECTOR_NAMES = ("body", "appendix")
DEVICE_MODE = EMBEDDING_SETTINGS.device_mode

RELATION_MODEL_SEARCH_PROFILES = {
    "law_to_case": {
        "default_score_multiplier": 1.0,
        "priority": "primary",
        "retrieval_role": "expansion",
    },
    "law_to_law": {
        "default_score_multiplier": 0.95,
        "priority": "primary",
        "retrieval_role": "linkage",
    },
    "case_to_case": {
        "default_score_multiplier": 0.75,
        "priority": "secondary",
        "retrieval_role": "trace",
    },
    "unknown": {
        "default_score_multiplier": 0.85,
        "priority": "secondary",
        "retrieval_role": "fallback",
    },
}
QUERY_RETRIEVAL_PROFILES = {
    "law_lookup": {
        "description": "법령명/조문 중심 질의",
        "collections": [
            {"name": "law_article", "enabled": True, "priority": 1, "score_multiplier": 1.0},
            {"name": "legal_case", "enabled": True, "priority": 2, "score_multiplier": 0.9},
            {
                "name": "legal_relation",
                "enabled": True,
                "priority": 3,
                "score_multiplier": 0.85,
                "relation_model_weights": {
                    "law_to_case": 1.0,
                    "law_to_law": 0.95,
                    "case_to_case": 0.6,
                },
            },
        ],
    },
    "case_lookup": {
        "description": "사건번호/판례 중심 질의",
        "collections": [
            {"name": "legal_case", "enabled": True, "priority": 1, "score_multiplier": 1.0},
            {
                "name": "legal_relation",
                "enabled": True,
                "priority": 2,
                "score_multiplier": 0.9,
                "relation_model_weights": {
                    "law_to_case": 0.8,
                    "law_to_law": 0.7,
                    "case_to_case": 1.0,
                },
            },
            {"name": "law_article", "enabled": True, "priority": 3, "score_multiplier": 0.75},
        ],
    },
    "citation_trace": {
        "description": "판례 인용/계보 추적 질의",
        "collections": [
            {
                "name": "legal_relation",
                "enabled": True,
                "priority": 1,
                "score_multiplier": 1.0,
                "relation_model_weights": {
                    "law_to_case": 0.7,
                    "law_to_law": 0.5,
                    "case_to_case": 1.0,
                },
            },
            {"name": "legal_case", "enabled": True, "priority": 2, "score_multiplier": 0.95},
            {"name": "law_article", "enabled": False, "priority": 3, "score_multiplier": 0.0},
        ],
    },
}


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


def _iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _classify_kind_name(kind_name: object) -> str | None:
    text = str(kind_name or "").strip()
    if not text:
        return None
    if "법률" in text:
        return "법"
    if "대통령령" in text:
        return "시행령"
    if "부령" in text or text.endswith("규칙"):
        return "시행규칙"
    if any(token in text for token in ("훈령", "예규", "고시", "규정", "지침", "지시")):
        return "행정규칙"
    return None


def _stable_law_level(row: dict) -> str | None:
    value = row.get("law_level") or row.get("classified_level") or _classify_kind_name(row.get("kind_name"))
    if value in (None, ""):
        return None
    return str(value).strip()


def _iter_collection_rows(dataset_dir: Path, collection_name: str) -> Iterator[dict]:
    legal_corpus_path = dataset_dir / "legal_corpus.jsonl"
    relation_path = dataset_dir / "legal_relations.jsonl"

    if collection_name == "law_article":
        for row in _iter_jsonl(legal_corpus_path):
            if row.get("doc_type") == "law":
                yield row
        return

    if collection_name == "legal_case":
        for row in _iter_jsonl(legal_corpus_path):
            if row.get("doc_type") in CASE_DOC_TYPES:
                yield row
        return

    if collection_name == "legal_relation":
        yield from _iter_jsonl(relation_path)
        return

    raise ValueError(f"Unsupported collection_name: {collection_name}")


def _canonical_id_from_row(row: dict) -> str:
    return canonical_id_from_row(row)


def _build_point_id(row: dict, duplicate_canonical_ids: set[str]) -> str:
    return build_qdrant_point_id(row, duplicate_canonical_ids)


def _scan_collection(dataset_dir: Path, collection_name: str) -> dict:
    canonical_id_counter: Counter[str] = Counter()
    doc_type_counter: Counter[str] = Counter()
    relation_model_counter: Counter[str] = Counter()
    row_count = 0
    text_row_count = 0

    for row in _iter_collection_rows(dataset_dir, collection_name):
        row_count += 1
        doc_type_counter[str(row.get("doc_type") or "")] += 1
        if collection_name == "legal_relation":
            relation_model_counter[str(row.get("relation_model") or "unknown")] += 1
        text = str(row.get("text") or "").strip()
        if collection_name == "law_article":
            appendix_text = str(row.get("appendix_vector_text") or APPENDIX_VECTOR_PLACEHOLDER).strip()
            if text or appendix_text:
                text_row_count += 1
        else:
            if text:
                text_row_count += 1
        canonical_id_counter[_canonical_id_from_row(row)] += 1

    duplicate_canonical_ids = {cid for cid, count in canonical_id_counter.items() if count > 1}
    return {
        "row_count": row_count,
        "text_row_count": text_row_count,
        "canonical_id_counter": canonical_id_counter,
        "duplicate_canonical_ids": duplicate_canonical_ids,
        "doc_type_counter": doc_type_counter,
        "relation_model_counter": relation_model_counter,
    }


def _relation_model_profile(row: dict) -> dict:
    relation_model = str(row.get("relation_model") or "unknown").strip() or "unknown"
    return dict(RELATION_MODEL_SEARCH_PROFILES.get(relation_model, RELATION_MODEL_SEARCH_PROFILES["unknown"]))


def _build_meta(collection_name: str, row: dict, point_id: str, text: str) -> dict:
    doc_type = row.get("doc_type")
    canonical_id = _canonical_id_from_row(row)
    relation_profile = _relation_model_profile(row) if collection_name == "legal_relation" else {}
    meta = {
        "id": row.get("id"),
        "canonical_id": canonical_id,
        "canonical_case_id": row.get("canonical_case_id"),
        "_point_id": point_id,
        "collection_name": collection_name,
        "doc_type": doc_type,
        "doc_type_label": row.get("doc_type_label"),
        "case_type": doc_type if collection_name == "legal_case" else None,
        "case_type_label": row.get("doc_type_label") if collection_name == "legal_case" else None,
        "law_name": row.get("law_name"),
        "law_id": row.get("law_id"),
        "mst": row.get("mst"),
        "ef_yd": row.get("ef_yd"),
        "kind_name": row.get("kind_name"),
        "classified_level": row.get("classified_level") or _stable_law_level(row),
        "law_level": _stable_law_level(row),
        "source_group": row.get("source_group"),
        "part_type": row.get("part_type"),
        "section_type": row.get("section_type"),
        "article_no": row.get("article_no"),
        "article_no_display": row.get("article_no_display"),
        "article_key": row.get("article_key"),
        "root_law_name": row.get("root_law_name"),
        "related_law_name": row.get("related_law_name"),
        "related_law_names": row.get("related_law_names"),
        "source_law_name": row.get("source_law_name"),
        "relation_model": row.get("relation_model"),
        "relation_type": row.get("relation_type"),
        "relation_types": row.get("relation_types"),
        "title": row.get("title"),
        "doc_id": row.get("doc_id"),
        "doc_number": row.get("doc_number"),
        "source_canonical_case_id": row.get("source_canonical_case_id"),
        "target_canonical_case_id": row.get("target_canonical_case_id"),
        "referenced_case_number": row.get("referenced_case_number"),
        "doc_kind": row.get("doc_kind"),
        "detail_link": row.get("detail_link"),
        "target": row.get("target"),
        "decision_date": row.get("decision_date"),
        "law_uid": row.get("law_uid"),
        "source_law_uid": row.get("source_law_uid"),
        "root_law_uid": row.get("root_law_uid"),
        "article_keys": row.get("article_keys"),
        "article_no_displays": row.get("article_no_displays"),
        "relation_confidence": row.get("relation_confidence"),
        "source_hit_count": row.get("source_hit_count"),
        "source_file_path": row.get("source_file_path"),
        "chunk_index": row.get("chunk_index"),
        "text_len": len(text),
        "search_text": row.get("search_text"),
        "display_text": row.get("display_text"),
        "updated_at": row.get("updated_at"),
        "delta_batch_id": row.get("delta_batch_id"),
        "default_score_multiplier": relation_profile.get("default_score_multiplier"),
        "relation_model_priority": relation_profile.get("priority"),
        "retrieval_role": relation_profile.get("retrieval_role"),
    }

    if collection_name == "law_article":
        meta.update(
            {
                "has_related_appendix": bool(row.get("has_related_appendix")),
                "related_appendix_count": int(row.get("related_appendix_count") or 0),
                "related_appendix_ids": row.get("related_appendix_ids") or [],
                "related_appendix_keys": row.get("related_appendix_keys") or [],
                "related_appendix_nos": row.get("related_appendix_nos") or [],
                "related_appendix_titles": row.get("related_appendix_titles") or [],
                "related_appendix_match_types": row.get("related_appendix_match_types") or [],
                "related_appendix_previews": row.get("related_appendix_previews") or [],
                "related_appendices": row.get("related_appendices") or [],
                "appendix_vector_text_len": len(str(row.get("appendix_vector_text") or APPENDIX_VECTOR_PLACEHOLDER)),
            }
        )

    return meta


def _write_variant_source(handoff_dir: Path, collection_name: str, source_rows: Sequence[dict]) -> Path:
    source_dir = handoff_dir / "source"
    source_path = source_dir / f"{collection_name}.jsonl"
    write_jsonl(source_path, source_rows)
    return source_path


def _write_variant_import(handoff_dir: Path, collection_name: str, import_rows: Sequence[dict]) -> Path:
    import_dir = handoff_dir / "import"
    import_path = import_dir / f"{collection_name}_for_import.jsonl"
    write_jsonl(import_path, import_rows)
    return import_path


def _iter_law_article_rows(dataset_dir: Path) -> list[dict]:
    return list(_iter_collection_rows(dataset_dir, "law_article"))


def _iter_simple_rows(dataset_dir: Path, collection_name: str) -> list[dict]:
    return list(_iter_collection_rows(dataset_dir, collection_name))


def _encode(model, texts: list[str], batch_size: int) -> np.ndarray:
    return model.encode(texts, batch_size=batch_size)


def _build_law_article_import_rows(
    metas: Sequence[dict],
    body_texts: Sequence[str],
    appendix_texts: Sequence[str],
    body_embeddings: np.ndarray,
    appendix_embeddings: np.ndarray,
    *,
    embedding_model: str,
    embedding_provider: str,
) -> list[dict]:
    rows: list[dict] = []
    for meta, body_text, appendix_text, body_vector, appendix_vector in zip(
        metas,
        body_texts,
        appendix_texts,
        body_embeddings,
        appendix_embeddings,
        strict=True,
    ):
        row = dict(meta)
        row["text"] = body_text
        row["appendix_vector_text"] = appendix_text
        row["_vectors"] = {
            "body": body_vector.astype(np.float32).tolist(),
            "appendix": appendix_vector.astype(np.float32).tolist(),
        }
        row["_score"] = None
        row["embedding_model"] = embedding_model
        row["embedding_provider"] = embedding_provider
        row["embedding_passage_prefix"] = EMBEDDING_PASSAGE_PREFIX
        row["normalized"] = NORMALIZE_EMBEDDINGS
        rows.append(row)
    return rows


def _build_simple_import_rows(
    metas: Sequence[dict],
    texts: Sequence[str],
    embeddings: np.ndarray,
    *,
    embedding_model: str,
    embedding_provider: str,
) -> list[dict]:
    rows: list[dict] = []
    for meta, text, vector in zip(metas, texts, embeddings, strict=True):
        row = dict(meta)
        row["text"] = text
        row["_vector"] = vector.astype(np.float32).tolist()
        row["_score"] = None
        row["embedding_model"] = embedding_model
        row["embedding_provider"] = embedding_provider
        row["embedding_passage_prefix"] = EMBEDDING_PASSAGE_PREFIX
        row["normalized"] = NORMALIZE_EMBEDDINGS
        rows.append(row)
    return rows


def _build_retrieval_policy(
    collection_manifests: Sequence[dict],
) -> dict:
    enabled_collections = {
        str(item.get("collection_name") or "")
        for item in collection_manifests
        if not bool(item.get("skipped"))
    }
    query_profiles: dict[str, dict] = {}

    for profile_name, profile in QUERY_RETRIEVAL_PROFILES.items():
        configured_collections: list[dict] = []
        for collection in profile["collections"]:
            collection_entry = dict(collection)
            collection_entry["available"] = collection_entry["name"] in enabled_collections
            configured_collections.append(collection_entry)

        query_profiles[profile_name] = {
            "description": profile["description"],
            "collections": configured_collections,
        }

    return {
        "default_query_profile": "law_lookup",
        "notes": [
            "relation rows are supporting evidence and should not outrank primary corpus hits by default",
            "case_to_case relations are intended for citation tracing and case-number-driven queries",
        ],
        "relation_model_profiles": RELATION_MODEL_SEARCH_PROFILES,
        "query_profiles": query_profiles,
    }


def embed_law_article(
    model,
    dataset_dir: Path,
    emb_dir: Path,
    handoff_dir: Path,
    *,
    batch_size: int,
) -> dict:
    collection_name = "law_article"
    rows = _iter_law_article_rows(dataset_dir)
    canonical_id_counter: Counter[str] = Counter(_canonical_id_from_row(r) for r in rows)
    duplicate_canonical_ids: set[str] = {cid for cid, n in canonical_id_counter.items() if n > 1}

    metas: list[dict] = []
    body_texts: list[str] = []
    appendix_texts: list[str] = []
    source_rows: list[dict] = []

    for row in rows:
        body_text = str(row.get("text") or "").strip()
        if not body_text:
            continue
        appendix_text = str(row.get("appendix_vector_text") or APPENDIX_VECTOR_PLACEHOLDER).strip() or APPENDIX_VECTOR_PLACEHOLDER
        point_id = _build_point_id(row, duplicate_canonical_ids)
        meta = _build_meta(collection_name, row, point_id, body_text)
        metas.append(meta)
        body_texts.append(body_text)
        appendix_texts.append(appendix_text)
        source_rows.append(dict(row))

    if not body_texts:
        raise ValueError("[law_article] no texts found to embed")

    body_embeddings = _encode(model, body_texts, batch_size)
    appendix_embeddings = _encode(model, appendix_texts, batch_size)

    emb_dir.mkdir(parents=True, exist_ok=True)
    body_npy_path = emb_dir / f"{collection_name}.body.npy"
    appendix_npy_path = emb_dir / f"{collection_name}.appendix.npy"
    meta_path = emb_dir / f"{collection_name}.meta.jsonl"
    manifest_path = emb_dir / f"{collection_name}.manifest.json"

    np.save(body_npy_path, body_embeddings)
    np.save(appendix_npy_path, appendix_embeddings)
    write_jsonl(meta_path, metas)

    import_rows = _build_law_article_import_rows(
        metas,
        body_texts,
        appendix_texts,
        body_embeddings,
        appendix_embeddings,
        embedding_model=model.model_name,
        embedding_provider=model.provider,
    )
    source_path = _write_variant_source(handoff_dir, collection_name, source_rows)
    import_path = _write_variant_import(handoff_dir, collection_name, import_rows)

    manifest = {
        "collection_name": collection_name,
        "model_name": model.model_name,
        "embedding_provider": model.provider,
        "count": len(metas),
        "embedding_dim": int(body_embeddings.shape[1]) if len(body_embeddings) else 0,
        "normalized": NORMALIZE_EMBEDDINGS,
        "dtype": "float32",
        "batch_size": batch_size,
        "vector_names": list(LAW_ARTICLE_VECTOR_NAMES),
        "dataset_dir": str(dataset_dir),
        "body_npy_path": str(body_npy_path),
        "appendix_npy_path": str(appendix_npy_path),
        "meta_path": str(meta_path),
        "source_jsonl_path": str(source_path),
        "import_jsonl_path": str(import_path),
    }
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def embed_simple_collection(
    model,
    dataset_dir: Path,
    emb_dir: Path,
    handoff_dir: Path,
    collection_name: str,
    *,
    batch_size: int,
) -> dict:
    rows = _iter_simple_rows(dataset_dir, collection_name)
    canonical_id_counter: Counter[str] = Counter(_canonical_id_from_row(r) for r in rows)
    duplicate_canonical_ids: set[str] = {cid for cid, n in canonical_id_counter.items() if n > 1}
    relation_model_counter: Counter[str] = (
        Counter(str(r.get("relation_model") or "unknown") for r in rows)
        if collection_name == "legal_relation"
        else Counter()
    )

    metas: list[dict] = []
    texts: list[str] = []
    source_rows: list[dict] = []

    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        point_id = _build_point_id(row, duplicate_canonical_ids)
        meta = _build_meta(collection_name, row, point_id, text)
        metas.append(meta)
        texts.append(text)
        source_rows.append(dict(row))

    if not texts:
        print(f"[skip] {collection_name}: no texts found to embed")
        return {
            "collection_name": collection_name,
            "count": 0,
            "skipped": True,
            "reason": "no texts found to embed",
        }

    embeddings = _encode(model, texts, batch_size)

    emb_dir.mkdir(parents=True, exist_ok=True)
    npy_path = emb_dir / f"{collection_name}.npy"
    meta_path = emb_dir / f"{collection_name}.meta.jsonl"
    manifest_path = emb_dir / f"{collection_name}.manifest.json"

    np.save(npy_path, embeddings)
    write_jsonl(meta_path, metas)

    import_rows = _build_simple_import_rows(
        metas,
        texts,
        embeddings,
        embedding_model=model.model_name,
        embedding_provider=model.provider,
    )
    source_path = _write_variant_source(handoff_dir, collection_name, source_rows)
    import_path = _write_variant_import(handoff_dir, collection_name, import_rows)

    manifest = {
        "collection_name": collection_name,
        "model_name": model.model_name,
        "embedding_provider": model.provider,
        "count": len(metas),
        "embedding_dim": int(embeddings.shape[1]) if len(embeddings) else 0,
        "normalized": NORMALIZE_EMBEDDINGS,
        "dtype": "float32",
        "batch_size": batch_size,
        "vector_names": ["default"],
        "dataset_dir": str(dataset_dir),
        "npy_path": str(npy_path),
        "meta_path": str(meta_path),
        "source_jsonl_path": str(source_path),
        "import_jsonl_path": str(import_path),
    }
    if collection_name == "legal_relation":
        manifest["relation_model_counts"] = dict(relation_model_counter)
        manifest["relation_model_profiles"] = RELATION_MODEL_SEARCH_PROFILES
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def write_embedding_manifest(
    handoff_dir: Path,
    dataset_dir: Path,
    emb_dir: Path,
    collection_manifests: Sequence[dict],
) -> Path:
    manifest_path = handoff_dir / "qdrant_embedding_manifest.json"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    embedding_dim = max((int(item.get("embedding_dim") or 0) for item in collection_manifests), default=0)
    model_name = next((str(item.get("model_name") or "") for item in collection_manifests if item.get("model_name")), MODEL_NAME)
    embedding_provider = next(
        (str(item.get("embedding_provider") or "") for item in collection_manifests if item.get("embedding_provider")),
        EMBEDDING_PROVIDER,
    )
    payload = {
        "model_name": model_name,
        "embedding_provider": embedding_provider,
        "embedding_dim": embedding_dim,
        "normalized": NORMALIZE_EMBEDDINGS,
        "dtype": "float32",
        "metric": "cosine",
        "embedding_passage_prefix": EMBEDDING_PASSAGE_PREFIX,
        "dataset_dir": str(dataset_dir),
        "emb_dir": str(emb_dir),
        "collections": list(collection_manifests),
        "retrieval_policy": _build_retrieval_policy(collection_manifests),
    }
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed Qdrant 3-collection handoff files.")
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=Path("data/dataset"),
        help="Dataset directory containing legal_corpus.jsonl and legal_relations.jsonl.",
    )
    parser.add_argument(
        "--emb-dir",
        type=Path,
        default=Path("data/emb/qdrant_3collections"),
        help="Directory to write .npy and meta outputs.",
    )
    parser.add_argument(
        "--handoff-dir",
        type=Path,
        default=Path("data/handoff/qdrant_3collections"),
        help="Directory to write source/import JSONL and collection manifest.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Embedding encode batch size.",
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

    print(f"[embed] provider={EMBEDDING_PROVIDER} model={MODEL_NAME} device_mode={DEVICE_MODE}")

    model = create_embedding_backend(EMBEDDING_SETTINGS)

    try:
        collection_manifests: list[dict] = []
        collection_manifests.append(
            embed_law_article(
                model=model,
                dataset_dir=dataset_dir,
                emb_dir=emb_dir,
                handoff_dir=handoff_dir,
                batch_size=batch_size,
            )
        )
        for collection_name in ("legal_case",):
            collection_manifests.append(
                embed_simple_collection(
                    model=model,
                    dataset_dir=dataset_dir,
                    emb_dir=emb_dir,
                    handoff_dir=handoff_dir,
                    collection_name=collection_name,
                    batch_size=batch_size,
                )
            )

        write_embedding_manifest(
            handoff_dir=handoff_dir,
            dataset_dir=dataset_dir,
            emb_dir=emb_dir,
            collection_manifests=collection_manifests,
        )
    finally:
        model.close()


if __name__ == "__main__":
    main()
