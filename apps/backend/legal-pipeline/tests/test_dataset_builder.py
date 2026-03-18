from src.common.io_utils import _write_json
from src.export.dataset_builder import build_law_records


def test_build_law_records_normalizes_kind_name_and_avoids_duplicate_ids(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "건설산업기본법"
    parsed_path = normalized_dir / "건설산업기본법__parsed_law.json"

    _write_json(
        parsed_path,
        {
            "law_name": "건설산업기본법",
            "law_id": "001808",
            "mst": "273435",
            "ef_yd": "20251127",
            "kind_name": "{'content': '대통령령', '법종구분코드': 'A0007'}",
            "classified_level": "시행령",
            "articles": [
                {
                    "jo_code": "2",
                    "article_no": "제2조",
                    "article_no_display": "제2조",
                    "article_key": "2",
                    "article_title_raw": "정의",
                    "article_title": "정의",
                    "article_text_raw": "정의 조문",
                    "article_text": "정의 조문",
                    "paragraphs": [],
                },
                {
                    "jo_code": "2",  # 일부 원천 데이터처럼 충돌 상황 가정
                    "article_no": "제8조",
                    "article_no_display": "제8조",
                    "article_key": "8",
                    "article_title_raw": "건설사업자",
                    "article_title": "건설사업자",
                    "article_text_raw": "건설사업자 조문",
                    "article_text": "건설사업자 조문",
                    "paragraphs": [],
                },
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

    assert len(records) == 2
    assert len({record["id"] for record in records}) == 2
    assert all(record["kind_name"] == "대통령령" for record in records)
    assert all(record["classified_level"] == "시행령" for record in records)
    assert all(record["law_level"] == "시행령" for record in records)