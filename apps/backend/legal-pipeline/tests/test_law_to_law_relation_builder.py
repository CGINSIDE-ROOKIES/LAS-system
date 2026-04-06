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


def test_build_law_to_law_relation_records_extracts_same_law_and_external_refs(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"

    _write_json(
        normalized_dir / "근로기준법__parsed_law.json",
        {
            "law_name": "근로기준법",
            "law_id": "001872",
            "mst": "269390",
            "ef_yd": "20250223",
            "kind_name": "법률",
            "classified_level": "법",
            "articles": [
                {
                    "article_key": "3",
                    "article_no": "제3조",
                    "article_no_display": "제3조",
                    "article_title": "정의",
                    "article_title_raw": "정의",
                    "article_text": "정의를 정한다.",
                    "article_text_raw": "정의를 정한다.",
                },
                {
                    "article_key": "4",
                    "article_no": "제4조",
                    "article_no_display": "제4조",
                    "article_title": "근로조건",
                    "article_title_raw": "근로조건",
                    "article_text": "전조 및 민법 제750조를 따른다.",
                    "article_text_raw": "전조 및 민법 제750조를 따른다.",
                },
            ],
        },
    )

    rows = build_law_to_law_relation_records(tmp_path / "normalized" / "01_current_law")
    rows_by_target = {row["law_name"]: row for row in rows}

    same_law_row = rows_by_target["근로기준법"]
    assert same_law_row["source_law_uid"] == same_law_row["law_uid"]
    assert "same_law_reference" in same_law_row["relation_types"]
    assert "relative_reference" in same_law_row["relation_types"]
    assert same_law_row["article_keys"] == ["3"]
    assert same_law_row["source_article_key"] == "4"
    assert same_law_row["resolution_status"] == "resolved"
    assert same_law_row["reference_texts"] == ["전조"]

    external_row = rows_by_target["민법"]
    assert external_row["law_uid"] is None
    assert external_row["relation_type"] == "related_law"
    assert "external_reference" in external_row["relation_types"]
    assert external_row["article_keys"] == ["750"]
    assert external_row["resolution_status"] == "unresolved_external"


def test_build_law_to_law_relation_records_recovers_noisy_scope_reference_as_family_law(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "건설산업기본법"

    _write_json(
        normalized_dir / "건설산업기본법_시행령__parsed_law.json",
        {
            "law_name": "건설산업기본법 시행령",
            "law_id": "002115",
            "mst": "269999",
            "ef_yd": "20250223",
            "kind_name": "대통령령",
            "classified_level": "시행령",
            "articles": [
                {
                    "article_key": "43",
                    "article_no": "제43조",
                    "article_no_display": "제43조",
                    "article_title": "하도급계약의 특례",
                    "article_title_raw": "하도급계약의 특례",
                    "article_text": "제43조(하도급계약의 특례) 법 제48조에 따른다.",
                    "article_text_raw": "제43조(하도급계약의 특례) 법 제48조에 따른다.",
                }
            ],
        },
    )
    _write_json(
        normalized_dir / "건설산업기본법__parsed_law.json",
        {
            "law_name": "건설산업기본법",
            "law_id": "000261",
            "mst": "269998",
            "articles": [],
        },
    )

    rows = build_law_to_law_relation_records(tmp_path / "normalized" / "01_current_law")

    assert len(rows) == 1
    row = rows[0]
    assert row["law_name"] == "건설산업기본법"
    assert row["article_keys"] == ["48"]
    assert row["resolution_status"] == "resolved"
    assert "relative_reference" in row["relation_types"]
