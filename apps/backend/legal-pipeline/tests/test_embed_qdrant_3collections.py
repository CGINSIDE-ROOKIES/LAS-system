import json
from pathlib import Path

from src.common.io_utils import _write_jsonl
from scripts.embed_qdrant_3collections import (
    _build_meta,
    _build_retrieval_policy,
    _scan_collection,
    write_embedding_manifest,
)


def test_scan_collection_tracks_relation_model_counts(tmp_path):
    dataset_dir = tmp_path / "dataset"
    _write_jsonl(
        dataset_dir / "legal_relations.jsonl",
        [
            {
                "id": "relation::case::prec::123456::law-001",
                "canonical_id": "case::prec::123456",
                "canonical_case_id": "case::prec::123456",
                "doc_type": "relation",
                "relation_model": "law_to_case",
                "text": "law relation",
            },
            {
                "id": "case_relation::case::prec::123456::case::prec::777777",
                "canonical_id": "case::prec::123456",
                "canonical_case_id": "case::prec::123456",
                "doc_type": "relation",
                "relation_model": "case_to_case",
                "text": "case relation",
            },
        ],
    )
    _write_jsonl(dataset_dir / "legal_corpus.jsonl", [])

    stats = _scan_collection(dataset_dir, "legal_relation")

    assert stats["relation_model_counter"]["law_to_case"] == 1
    assert stats["relation_model_counter"]["case_to_case"] == 1


def test_build_meta_includes_relation_model_search_profile():
    row = {
        "id": "case_relation::case::prec::123456::case::prec::777777",
        "canonical_id": "case::prec::123456",
        "canonical_case_id": "case::prec::123456",
        "doc_type": "relation",
        "doc_type_label": "판례",
        "relation_model": "case_to_case",
        "relation_type": "cited_case",
        "relation_types": ["cited_case"],
        "source_canonical_case_id": "case::prec::123456",
        "target_canonical_case_id": "case::prec::777777",
        "referenced_case_number": "2018다12345",
        "text": "case relation",
    }

    meta = _build_meta("legal_relation", row, "point-1", row["text"])

    assert meta["relation_model"] == "case_to_case"
    assert meta["default_score_multiplier"] == 0.75
    assert meta["relation_model_priority"] == "secondary"
    assert meta["retrieval_role"] == "trace"


def test_build_meta_includes_law_to_law_search_profile():
    row = {
        "id": "relation::law::source-law::target-law::16",
        "canonical_id": "relation::law::source-law::target-law::16",
        "doc_type": "relation",
        "relation_model": "law_to_law",
        "relation_type": "related_law",
        "relation_types": ["related_law"],
        "text": "law to law relation",
    }

    meta = _build_meta("legal_relation", row, "point-law", row["text"])

    assert meta["relation_model"] == "law_to_law"
    assert meta["default_score_multiplier"] == 0.95
    assert meta["relation_model_priority"] == "primary"
    assert meta["retrieval_role"] == "linkage"


def test_build_retrieval_policy_marks_collection_availability_and_weights():
    policy = _build_retrieval_policy(
        [
            {"collection_name": "law_article", "skipped": False},
            {"collection_name": "legal_case", "skipped": False},
            {"collection_name": "legal_relation", "skipped": False},
        ]
    )

    assert policy["default_query_profile"] == "law_lookup"
    assert policy["relation_model_profiles"]["case_to_case"]["default_score_multiplier"] == 0.75
    citation_profile = policy["query_profiles"]["citation_trace"]
    assert citation_profile["collections"][0]["name"] == "legal_relation"
    assert citation_profile["collections"][0]["relation_model_weights"]["case_to_case"] == 1.0
    assert policy["query_profiles"]["law_lookup"]["collections"][2]["relation_model_weights"]["law_to_law"] == 0.95
    assert all(item["available"] is True for item in citation_profile["collections"][:2])


def test_build_retrieval_policy_marks_legal_relation_unavailable_when_not_embedded():
    policy = _build_retrieval_policy(
        [
            {"collection_name": "law_article", "skipped": False},
            {"collection_name": "legal_case", "skipped": False},
        ]
    )

    law_lookup = policy["query_profiles"]["law_lookup"]["collections"]
    citation_trace = policy["query_profiles"]["citation_trace"]["collections"]

    assert law_lookup[0]["name"] == "law_article"
    assert law_lookup[0]["available"] is True
    assert law_lookup[1]["name"] == "legal_case"
    assert law_lookup[1]["available"] is True
    assert law_lookup[2]["name"] == "legal_relation"
    assert law_lookup[2]["available"] is False
    assert citation_trace[0]["name"] == "legal_relation"
    assert citation_trace[0]["available"] is False


def test_write_embedding_manifest_uses_collection_dim(tmp_path):
    manifest_path = write_embedding_manifest(
        handoff_dir=tmp_path / "handoff",
        dataset_dir=tmp_path / "dataset",
        emb_dir=tmp_path / "emb",
        collection_manifests=[
            {
                "collection_name": "law_article",
                "model_name": "text-embedding-3-large",
                "embedding_dim": 1024,
            }
        ],
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["model_name"] == "text-embedding-3-large"
    assert payload["embedding_dim"] == 1024
