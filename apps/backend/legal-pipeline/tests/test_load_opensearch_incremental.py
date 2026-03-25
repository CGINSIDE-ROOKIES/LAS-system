import json

from src.common.io_utils import _write_json, _write_jsonl
from scripts.upload.load_opensearch_incremental import build_incremental_bulk_files


def test_build_incremental_bulk_files_writes_collection_specific_ndjson(tmp_path):
    patch_dir = tmp_path / "patch" / "20260325"
    _write_json(
        patch_dir / "delta_manifest.json",
        {
            "delta_batch_id": "20260325",
            "legal_corpus_upsert_count": 2,
            "legal_corpus_delete_count": 1,
            "legal_relations_upsert_count": 1,
            "legal_relations_delete_count": 0,
        },
    )
    _write_jsonl(
        patch_dir / "legal_corpus.upsert.jsonl",
        [
            {
                "id": "law::1",
                "_point_id": "law::1::article::1",
                "doc_type": "law",
                "text": "근로기준법 제1조",
            },
            {
                "id": "case_chunk::case::prec::1::0",
                "_point_id": "case::prec::1",
                "doc_type": "prec",
                "text": "판례 본문",
            },
        ],
    )
    _write_jsonl(
        patch_dir / "legal_corpus.delete.jsonl",
        [
            {
                "id": "case_chunk::case::prec::2::0",
                "_point_id": "case::prec::2",
                "doc_type": "prec",
            }
        ],
    )
    _write_jsonl(
        patch_dir / "legal_relations.upsert.jsonl",
        [
            {
                "id": "relation::1",
                "_point_id": "case::prec::1::ctx::abc",
                "collection_name": "legal_relation",
                "doc_type": "relation",
                "text": "관계 본문",
            }
        ],
    )
    _write_jsonl(patch_dir / "legal_relations.delete.jsonl", [])

    output_dir = tmp_path / "handoff" / "opensearch_incremental" / "20260325"
    manifest = build_incremental_bulk_files(
        dataset_patch_dir=patch_dir,
        output_dir=output_dir,
    )

    assert manifest["delta_batch_id"] == "20260325"
    assert {item["collection_name"] for item in manifest["collections"]} == {
        "law_article",
        "legal_case",
        "legal_relation",
    }

    law_upsert_lines = [
        json.loads(line)
        for line in (output_dir / "law_article.upsert.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    case_delete_lines = [
        json.loads(line)
        for line in (output_dir / "legal_case.delete.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert law_upsert_lines[0]["index"]["_index"] == "law_article"
    assert law_upsert_lines[1]["point_id"] == "law::1::article::1"
    assert case_delete_lines[0]["delete"]["_id"] == "case::prec::2"

    written_manifest = json.loads(
        (output_dir / "opensearch_incremental_manifest.json").read_text(encoding="utf-8")
    )
    assert written_manifest["delta_batch_id"] == "20260325"
