from pytest import raises

from src.common.io_utils import _write_json, _write_jsonl
from src.export.dataset_validation import validate_appendix_merge_outputs


def test_validate_appendix_merge_outputs_writes_summary(tmp_path):
    output_dir = tmp_path / "dataset"
    manifest_path = tmp_path / "manifest" / "appendix_validation_summary.json"

    _write_jsonl(
        output_dir / "legal_corpus.jsonl",
        [
            {
                "id": "law::1::article::23::0",
                "doc_type": "law",
                "section_type": "article",
                "has_related_appendix": True,
                "related_appendices": [{"appendix_id": "appendix::1"}],
                "appendix_vector_text": "별표 내용",
            }
        ],
    )

    summary = validate_appendix_merge_outputs(
        output_dir=output_dir,
        manifest_path=manifest_path,
        dataset_manifest={
            "legal_corpus_count": 1,
            "law_record_count": 1,
            "related_doc_record_count": 0,
            "article_appendix_manifest": {
                "appendix_bundle_count": 1,
                "article_with_appendix_count": 1,
                "article_appendix_link_count": 1,
                "linked_appendix_count": 1,
                "unresolved_appendix_count": 0,
            },
        },
    )

    written = manifest_path.read_text(encoding="utf-8")
    assert '"status": "passed"' in written
    assert summary["checks"][0]["name"] == "article_appendix_manifest_present"


def test_validate_appendix_merge_outputs_fails_without_appendix_manifest(tmp_path):
    output_dir = tmp_path / "dataset"
    manifest_path = tmp_path / "manifest" / "appendix_validation_summary.json"

    _write_json(output_dir / "dataset_manifest.json", {"article_appendix_manifest": None})
    _write_jsonl(output_dir / "legal_corpus.jsonl", [])

    with raises(RuntimeError, match="article_appendix_manifest is missing"):
        validate_appendix_merge_outputs(
            output_dir=output_dir,
            manifest_path=manifest_path,
            dataset_manifest={"article_appendix_manifest": None},
        )
