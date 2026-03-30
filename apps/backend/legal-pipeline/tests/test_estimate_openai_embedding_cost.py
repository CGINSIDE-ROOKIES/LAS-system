from src.common.io_utils import _write_jsonl
from scripts.estimate_openai_embedding_cost import _build_cost_summary


def test_build_cost_summary_counts_corpus_case_relation_and_appendix(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "dataset"
    _write_jsonl(
        dataset_dir / "legal_corpus.jsonl",
        [
            {
                "doc_type": "law",
                "text": "abc",
                "appendix_vector_text": "wxyz",
            },
            {
                "doc_type": "prec",
                "text": "hello",
            },
        ],
    )
    _write_jsonl(
        dataset_dir / "legal_relations.jsonl",
        [
            {
                "doc_type": "relation",
                "text": "relation",
            }
        ],
    )

    def fake_load_token_counter(**kwargs):
        def count_tokens(text: str) -> int:
            return len(text.strip())

        return count_tokens, "rough_chars_per_token"

    monkeypatch.setattr(
        "scripts.estimate_openai_embedding_cost._load_token_counter",
        fake_load_token_counter,
    )

    payload = _build_cost_summary(
        dataset_dir,
        model_name="text-embedding-3-large",
        price_per_1m_tokens=0.13,
        allow_rough_estimate=True,
        chars_per_token=1.0,
    )

    assert payload["token_counter_mode"] == "rough_chars_per_token"
    assert payload["breakdown"]["law_article_body"] == {"rows": 1, "tokens": 3}
    assert payload["breakdown"]["law_article_appendix"] == {"rows": 1, "tokens": 4}
    assert payload["breakdown"]["legal_case"] == {"rows": 1, "tokens": 5}
    assert payload["breakdown"]["legal_relation"] == {"rows": 1, "tokens": 8}
    assert payload["breakdown"]["total"] == {"rows": 4, "tokens": 20}
