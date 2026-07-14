import json

from src.export.dataset_builder import build_incremental_dataset_patch


def test_build_incremental_dataset_patch_deletes_old_point_when_point_id_changes(tmp_path):
    previous_corpus_rows = [
        {
            "id": "case_chunk::case::prec::1::0",
            "canonical_id": "case::prec::1",
            "canonical_case_id": "case::prec::1",
            "doc_type": "prec",
            "title": "임금",
            "target": "prec",
            "chunk_index": 0,
            "text": "첫 번째 청크",
        },
        {
            "id": "case_chunk::case::prec::1::1",
            "canonical_id": "case::prec::1",
            "canonical_case_id": "case::prec::1",
            "doc_type": "prec",
            "title": "임금",
            "target": "prec",
            "chunk_index": 1,
            "text": "두 번째 청크",
        },
    ]
    current_corpus_rows = [
        {
            "id": "case_chunk::case::prec::1::0",
            "canonical_id": "case::prec::1",
            "canonical_case_id": "case::prec::1",
            "doc_type": "prec",
            "title": "임금",
            "target": "prec",
            "chunk_index": 0,
            "text": "첫 번째 청크",
        }
    ]

    manifest = build_incremental_dataset_patch(
        previous_corpus_rows=previous_corpus_rows,
        current_corpus_rows=current_corpus_rows,
        previous_relation_rows=[],
        current_relation_rows=[],
        patch_dir=tmp_path / "patch",
        delta_batch_id="20260324",
        updated_at="2026-03-24T12:00:00Z",
    )

    assert manifest["legal_corpus_upsert_count"] == 1
    assert manifest["legal_corpus_delete_count"] == 2

    upserts = [
        json.loads(line)
        for line in (tmp_path / "patch" / "legal_corpus.upsert.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    deletes = [
        json.loads(line)
        for line in (tmp_path / "patch" / "legal_corpus.delete.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert upserts[0]["collection_name"] == "legal_case"
    assert upserts[0]["delta_batch_id"] == "20260324"
    assert upserts[0]["_point_id"] == "case::prec::1"
    assert {row["id"] for row in deletes} == {
        "case_chunk::case::prec::1::0",
        "case_chunk::case::prec::1::1",
    }
    assert any(row["_point_id"].startswith("case::prec::1::ctx::") for row in deletes)


def test_build_incremental_dataset_patch_keeps_distinct_relation_point_ids(tmp_path):
    previous_relation_rows = [
        {
            "id": "case_relation::case::detc::124722::case::detc::137400",
            "canonical_id": "case::detc::124722",
            "canonical_case_id": "case::detc::124722",
            "relation_model": "case_to_case",
            "target_canonical_case_id": "case::detc::137400",
            "text": "relation a",
        },
        {
            "id": "case_relation::case::detc::124722::case::detc::151075",
            "canonical_id": "case::detc::124722",
            "canonical_case_id": "case::detc::124722",
            "relation_model": "case_to_case",
            "target_canonical_case_id": "case::detc::151075",
            "text": "relation b",
        },
    ]

    manifest = build_incremental_dataset_patch(
        previous_corpus_rows=[],
        current_corpus_rows=[],
        previous_relation_rows=[],
        current_relation_rows=previous_relation_rows,
        patch_dir=tmp_path / "patch",
        delta_batch_id="20260414",
        updated_at="2026-04-14T12:00:00Z",
    )

    assert manifest["legal_relations_upsert_count"] == 2

    upserts = [
        json.loads(line)
        for line in (tmp_path / "patch" / "legal_relations.upsert.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert {row["_point_id"] for row in upserts} == {
        "case_relation::case::detc::124722::case::detc::137400",
        "case_relation::case::detc::124722::case::detc::151075",
    }
