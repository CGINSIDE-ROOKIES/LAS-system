from src.common.io_utils import _write_json
from src.export.dataset_builder import build_law_records


def test_build_law_records_preserves_structure_by_default(tmp_path):
    parsed_law = {
        "law_name": "근로기준법",
        "law_id": "001",
        "articles": [
            {
                "jo_code": "000100",
                "article_no": "제1조",
                "article_title_raw": "목적",
                "article_title": "목적",
                "article_text_raw": "이 법은\n근로조건의 기준을 정한다.",
                "article_text": "이 법은\n근로조건의 기준을 정한다.",
                "paragraphs": [
                    {
                        "paragraph_no": "①",
                        "paragraph_text_raw": "사용자는\n근로자를 보호한다.",
                        "paragraph_text": "사용자는\n근로자를 보호한다.",
                        "items": [],
                    }
                ],
            }
        ],
        "supplementary": [],
        "appendices": [],
    }

    save_path = tmp_path / "normalized" / "근로기준법__parsed_law.json"
    _write_json(save_path, parsed_law)

    records = build_law_records(normalized_base_dir=tmp_path / "normalized")

    assert len(records) == 1
    assert records[0]["text_variant"] == "structure_preserved"
    assert "이 법은\n근로조건의 기준을 정한다." in records[0]["text"]
    assert "① 사용자는\n근로자를 보호한다." in records[0]["text"]


def test_build_law_records_can_emit_flat_variant(tmp_path):
    parsed_law = {
        "law_name": "근로기준법",
        "law_id": "001",
        "articles": [
            {
                "jo_code": "000100",
                "article_no": "제1조",
                "article_title": "목적",
                "article_text": "이 법은\n근로조건의 기준을 정한다.",
                "paragraphs": [],
            }
        ],
        "supplementary": [],
        "appendices": [],
    }

    save_path = tmp_path / "normalized" / "근로기준법__parsed_law.json"
    _write_json(save_path, parsed_law)

    records = build_law_records(
        normalized_base_dir=tmp_path / "normalized",
        law_text_variant="flat",
    )

    assert len(records) == 1
    assert records[0]["text_variant"] == "flat"
    assert "이 법은 근로조건의 기준을 정한다." in records[0]["text"]
    assert "이 법은\n근로조건의 기준을 정한다." not in records[0]["text"]
