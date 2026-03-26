import json

from scripts.upload.opensearch_common import (
    build_delete_ndjson,
    build_index_payload,
    build_opensearch_source,
    build_upsert_ndjson,
    opensearch_doc_id,
)


def test_build_opensearch_source_strips_vectors_and_normalizes_fields():
    row = {
        "id": "relation::1",
        "_point_id": "case::prec::1::ctx::abc",
        "collection_name": "legal_relation",
        "chunk_index": "3",
        "relation_confidence": "0.95",
        "search_text": "검색용 텍스트",
        "text": "",
        "_vector": [0.1, 0.2],
        "_score": 0.7,
    }

    source = build_opensearch_source(row, collection_name="legal_relation")

    assert source["point_id"] == "case::prec::1::ctx::abc"
    assert source["collection_name"] == "legal_relation"
    assert source["chunk_index"] == 3
    assert source["relation_confidence"] == 0.95
    assert source["text"] == "검색용 텍스트"
    assert "_point_id" not in source
    assert "_vector" not in source
    assert "_score" not in source


def test_build_index_payload_uses_nori_and_collection_specific_fields():
    payload = build_index_payload("law_article")
    analyzer = payload["settings"]["analysis"]["analyzer"]["kr_legal_nori"]
    properties = payload["mappings"]["properties"]

    assert analyzer["tokenizer"] == "nori_tokenizer"
    assert properties["text"]["analyzer"] == "kr_legal_nori"
    assert properties["point_id"]["type"] == "keyword"
    assert properties["article_no"]["type"] == "keyword"


def test_build_index_payload_allows_standard_tokenizer_fallback():
    payload = build_index_payload("law_article", tokenizer_name="standard", enable_nori_pos_filter=False)
    analyzer = payload["settings"]["analysis"]["analyzer"]["kr_legal_nori"]

    assert analyzer["tokenizer"] == "standard"
    assert analyzer["filter"] == ["lowercase"]


def test_bulk_ndjson_builders_generate_expected_actions():
    upsert_body, upsert_count = build_upsert_ndjson(
        [
            {
                "id": "law::1",
                "_point_id": "law::1::article::1",
                "text": "본문",
            }
        ],
        collection_name="law_article",
        index_name="law_article",
    )
    delete_body, delete_count = build_delete_ndjson(
        [{"_point_id": "law::1::article::1"}],
        index_name="law_article",
    )

    upsert_lines = [json.loads(line) for line in upsert_body.splitlines() if line.strip()]
    delete_lines = [json.loads(line) for line in delete_body.splitlines() if line.strip()]

    assert upsert_count == 1
    assert upsert_lines[0]["index"]["_index"] == "law_article"
    assert upsert_lines[1]["point_id"] == "law::1::article::1"

    assert delete_count == 1
    assert delete_lines[0]["delete"]["_id"] == "law::1::article::1"


def test_opensearch_doc_id_hashes_overlong_point_ids():
    long_point_id = "law::" + ("가" * 600)
    doc_id = opensearch_doc_id(long_point_id)

    assert doc_id.startswith("sha1::")
    assert doc_id != long_point_id
