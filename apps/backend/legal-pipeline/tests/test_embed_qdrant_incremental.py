import json

from src.common.io_utils import _write_jsonl
from scripts.embed_qdrant_incremental import build_incremental_embeddings


def test_build_incremental_embeddings_skips_model_load_when_no_upserts(tmp_path, monkeypatch):
    patch_dir = tmp_path / "patch"
    _write_jsonl(patch_dir / "legal_corpus.upsert.jsonl", [])
    _write_jsonl(
        patch_dir / "legal_corpus.delete.jsonl",
        [
            {
                "id": "law::001::article::1::0",
                "canonical_id": "law::001::article::1::0",
                "_point_id": "law::001::article::1::0",
                "doc_type": "law",
            }
        ],
    )
    _write_jsonl(patch_dir / "legal_relations.upsert.jsonl", [])
    _write_jsonl(patch_dir / "legal_relations.delete.jsonl", [])

    def fail_model_load(*args, **kwargs):
        raise AssertionError("embedding model should not be loaded for delete-only patches")

    monkeypatch.setattr("scripts.embed_qdrant_incremental.SentenceTransformer", fail_model_load)

    manifest = build_incremental_embeddings(
        dataset_patch_dir=patch_dir,
        emb_dir=tmp_path / "emb",
        handoff_dir=tmp_path / "handoff",
        delta_batch_id="20260324",
        batch_size=8,
    )

    assert manifest["corpus_upsert_count"] == 0
    assert all(item["skipped"] is True for item in manifest["collections"])

    delete_manifest = json.loads((tmp_path / "handoff" / "delete_manifest.json").read_text(encoding="utf-8"))
    assert delete_manifest["delta_batch_id"] == "20260324"
    assert delete_manifest["collections"]["law_article"] == [
        {
            "id": "law::001::article::1::0",
            "canonical_id": "law::001::article::1::0",
            "_point_id": "law::001::article::1::0",
        }
    ]
