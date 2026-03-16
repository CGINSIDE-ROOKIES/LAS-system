from src.collector.law_sub_article_collector import extract_jo_codes_from_parsed_law


def test_extract_jo_codes_from_parsed_law_uses_only_explicit_codes():
    parsed_law = {
        "articles": [
            {"jo_code": "000100", "article_no": "제1조"},
            {"jo_code": "000200", "article_no": "제2조"},
            {"article_no": "제3조"},
        ]
    }

    assert extract_jo_codes_from_parsed_law(parsed_law) == ["000100", "000200"]
