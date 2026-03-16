from src.common.io_utils import _write_json
from src.export.dataset_builder import build_law_records


def test_build_law_records_preserves_multiline_article_text(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"
    parsed_path = normalized_dir / "근로기준법__parsed_law.json"

    _write_json(
        parsed_path,
        {
            "law_name": "근로기준법",
            "law_id": "001",
            "mst": "mst001",
            "ef_yd": "20240101",
            "kind_name": "법률",
            "articles": [
                {
                    "jo_code": "000100",
                    "article_no": "제1조",
                    "article_title_raw": "목적",
                    "article_title": "목적",
                    "article_text_raw": "제1항 본문\n제1항 단서",
                    "article_text": "제1항 본문 제1항 단서",
                    "paragraphs": [
                        {
                            "paragraph_no": "①",
                            "paragraph_text_raw": "근로조건의 기준을 정한다.\n근로자의 기본적 생활을 보장한다.",
                            "paragraph_text": "근로조건의 기준을 정한다. 근로자의 기본적 생활을 보장한다.",
                            "items": [],
                        }
                    ],
                }
            ],
            "supplementary": [],
            "appendices": [],
        },
    )

    records = build_law_records(
        normalized_base_dir=tmp_path / "normalized" / "01_current_law",
        max_chars=500,
        overlap=50,
        text_variant="best",
        preserve_structure=True,
    )

    assert len(records) == 1
    assert "제1항 본문\n제1항 단서" in records[0]["text"]
    assert "① 근로조건의 기준을 정한다.\n" in records[0]["text"]
    assert records[0]["structure_preserved"] is True
