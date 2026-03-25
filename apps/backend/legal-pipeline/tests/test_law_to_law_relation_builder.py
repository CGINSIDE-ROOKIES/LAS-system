from src.common.io_utils import _write_json
from src.export.law_to_law_relation_builder import build_law_to_law_relation_records


def test_build_law_to_law_relation_records_extracts_explicit_law_and_article_refs(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"

    _write_json(
        normalized_dir / "근로기준법_시행규칙__parsed_law.json",
        {
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
            "ef_yd": "20250223",
            "kind_name": "고용노동부령",
            "classified_level": "시행규칙",
            "articles": [
                {
                    "article_key": "16",
                    "article_no": "제16조",
                    "article_no_display": "제16조",
                    "article_title": "서식",
                    "article_title_raw": "서식",
                    "article_text": "근로기준법 제28조 및 근로기준법 시행령 제11조에 따른다.",
                    "article_text_raw": "근로기준법 제28조 및 근로기준법 시행령 제11조에 따른다.",
                }
            ],
        },
    )
    _write_json(
        normalized_dir / "근로기준법__parsed_law.json",
        {
            "law_name": "근로기준법",
            "law_id": "001872",
            "mst": "269390",
            "articles": [],
        },
    )
    _write_json(
        normalized_dir / "근로기준법_시행령__parsed_law.json",
        {
            "law_name": "근로기준법 시행령",
            "law_id": "006860",
            "mst": "269394",
            "articles": [],
        },
    )

    rows = build_law_to_law_relation_records(tmp_path / "normalized" / "01_current_law")

    assert len(rows) == 2
    rows_by_target = {row["law_name"]: row for row in rows}

    law_row = rows_by_target["근로기준법"]
    assert law_row["relation_model"] == "law_to_law"
    assert law_row["relation_type"] == "related_law"
    assert law_row["law_uid"] == "001872"
    assert law_row["source_law_uid"] == "006859"
    assert law_row["article_keys"] == ["28"]
    assert law_row["article_no_displays"] == ["제28조"]
    assert "근로기준법 시행규칙" in law_row["text"]
    assert law_row["search_text"] == law_row["text"]
    assert law_row["display_text"]

    decree_row = rows_by_target["근로기준법 시행령"]
    assert decree_row["relation_model"] == "law_to_law"
    assert decree_row["article_keys"] == ["11"]
    assert decree_row["article_no_displays"] == ["제11조"]
