from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# Qdrant connection
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
QDRANT_TIMEOUT_SEC = float(os.getenv("QDRANT_TIMEOUT_SEC", "30"))

# Current embedding output layout
HANDOFF_DIR = Path(os.getenv("QDRANT_HANDOFF_DIR", PROJECT_ROOT / "data" / "handoff" / "qdrant_3collections"))
EMB_DIR = Path(os.getenv("QDRANT_EMB_DIR", PROJECT_ROOT / "data" / "emb" / "qdrant_3collections"))
IMPORT_DIR = HANDOFF_DIR / "import"
SOURCE_DIR = HANDOFF_DIR / "source"
EMBEDDING_MANIFEST_PATH = HANDOFF_DIR / "qdrant_embedding_manifest.json"

DEFAULT_VECTOR_DIM = 768
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
NORMALIZE = True
BATCH_SIZE = 500

HNSW_M = 16
HNSW_EF_CONSTRUCT = 128
INDEXING_THRESHOLD = 20_000


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_embedding_manifest() -> dict[str, Any]:
    if not EMBEDDING_MANIFEST_PATH.exists():
        return {}
    payload = _read_json(EMBEDDING_MANIFEST_PATH)
    return payload if isinstance(payload, dict) else {}


EMBEDDING_MANIFEST = _load_embedding_manifest()
VECTOR_DIM = int(EMBEDDING_MANIFEST.get("embedding_dim", DEFAULT_VECTOR_DIM))
EMBEDDING_MODEL = str(EMBEDDING_MANIFEST.get("model_name") or DEFAULT_EMBEDDING_MODEL)


def _default_collection_config(name: str) -> dict[str, Any]:
    if name == "law_article":
        return {
            "vector_mode": "named",
            "body_npy": EMB_DIR / "law_article.body.npy",
            "appendix_npy": EMB_DIR / "law_article.appendix.npy",
            "payload_jsonl": IMPORT_DIR / "law_article_for_import.jsonl",
            "query_vectors": ["body", "appendix"],
            "default_query_vector": "body",
        }

    return {
        "vector_mode": "single",
        "npy": EMB_DIR / f"{name}.npy",
        "payload_jsonl": IMPORT_DIR / f"{name}_for_import.jsonl",
    }


def _load_collection_manifest(name: str) -> dict[str, Any]:
    manifest_path = EMB_DIR / f"{name}.manifest.json"
    if not manifest_path.exists():
        return {}
    payload = _read_json(manifest_path)
    return payload if isinstance(payload, dict) else {}


def _build_collection_config(name: str) -> dict[str, Any]:
    config = _default_collection_config(name)
    manifest = _load_collection_manifest(name)
    if not manifest:
        return config

    if config["vector_mode"] == "named":
        config["body_npy"] = Path(manifest.get("body_npy_path") or config["body_npy"])
        config["appendix_npy"] = Path(manifest.get("appendix_npy_path") or config["appendix_npy"])
    else:
        config["npy"] = Path(manifest.get("npy_path") or config["npy"])

    config["payload_jsonl"] = Path(manifest.get("import_jsonl_path") or config["payload_jsonl"])
    config["meta_jsonl"] = Path(manifest.get("meta_path") or EMB_DIR / f"{name}.meta.jsonl")
    config["manifest_json"] = EMB_DIR / f"{name}.manifest.json"
    return config


COLLECTIONS = {
    name: _build_collection_config(name)
    for name in ("law_article", "legal_case", "legal_relation")
}


COMMON_KEYWORD_INDEX_FIELDS = [
    "id",
    "canonical_id",
    "canonical_case_id",
    "collection_name",
    "doc_type",
    "doc_type_label",
    "source_group",
    "part_type",
    "section_type",
    "law_name",
    "law_id",
    "law_uid",
    "source_law_uid",
    "root_law_name",
    "root_law_uid",
    "related_law_name",
    "related_law_names",
    "source_law_name",
    "kind_name",
    "classified_level",
    "law_level",
    "title",
    "doc_id",
    "doc_number",
    "doc_kind",
    "detail_link",
    "target",
    "decision_date",
    "delta_batch_id",
    "updated_at",
]

COMMON_INTEGER_INDEX_FIELDS = [
    "chunk_index",
    "text_len",
    "source_hit_count",
]

COMMON_FLOAT_INDEX_FIELDS = [
    "relation_confidence",
    "default_score_multiplier",
]

COLLECTION_KEYWORD_INDEX_FIELDS = {
    "law_article": COMMON_KEYWORD_INDEX_FIELDS + [
        "article_no",
        "article_no_display",
        "article_key",
    ],
    "legal_case": COMMON_KEYWORD_INDEX_FIELDS + [
        "case_type",
        "case_type_label",
    ],
    "legal_relation": COMMON_KEYWORD_INDEX_FIELDS + [
        "article_keys",
        "article_no_displays",
        "relation_model",
        "relation_type",
        "relation_types",
        "relation_model_priority",
        "retrieval_role",
        "source_canonical_case_id",
        "target_canonical_case_id",
        "referenced_case_number",
    ],
}

COLLECTION_INTEGER_INDEX_FIELDS = {
    "law_article": COMMON_INTEGER_INDEX_FIELDS + ["related_appendix_count"],
    "legal_case": COMMON_INTEGER_INDEX_FIELDS,
    "legal_relation": COMMON_INTEGER_INDEX_FIELDS,
}

COLLECTION_FLOAT_INDEX_FIELDS = {
    "law_article": [],
    "legal_case": [],
    "legal_relation": COMMON_FLOAT_INDEX_FIELDS,
}

DROP_FIELDS_ON_EXTRACT = {
    "_vector",
    "_vectors",
    "_score",
    "embedding_model",
    "embedding_passage_prefix",
    "normalized",
}

TEST_QUERIES = [
    "건설공사 도급 기준",
    "최저임금 인상률 기준은?",
    "근로기준법상 해고 예고 기간",
    "근로기준법 제43조의2 관련 판례",
    "2018다12345를 인용한 판례",
]
