from src.parser.appendix_api_markdown import parse_api_appendix_text


def test_parse_api_appendix_text_builds_markdown_tables_from_box_text():
    text_raw = "\n".join(
        [
            "근로감독관증의 규격, 양식, 색채 및 기재사항(제2조 관련)",
            "1. 규격, 양식 및 색채",
            "┌───────┬──────────┐",
            "│구분    │색도      │",
            "├───────┼──────────┤",
            "│A       │K 7%      │",
            "├───────┼──────────┤",
            "│글자색  │K(Black)  │",
            "└───────┴──────────┘",
            "※ C(Cyan): 푸른색",
        ]
    )

    parsed = parse_api_appendix_text(text_raw, title="근로감독관증의 규격")

    assert parsed["table_count"] == 1
    assert parsed["markdown_tables"]
    assert parsed["markdown_tables"][0].startswith("| 구분 | 색도 |")
    assert "| A | K 7% |" in parsed["markdown_tables"][0]
    assert parsed["document_markdown"].startswith("# 근로감독관증의 규격")
    assert "## 1. 규격, 양식 및 색채" in parsed["document_markdown"]
    assert "### 표 1" in parsed["document_markdown"]
