from src.common.io_utils import _write_json
from src.export.dataset_builder import build_law_records
from src.parser.law_parser import parse_law_body


def test_parse_law_body_derives_article_display_and_key_from_body_text():
    raw_detail = {
        "법령": {
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "43",
                        "조문제목": "체불사업주 명단 공개",
                        "조문내용": "제43조의2(체불사업주 명단 공개) 본문",
                    }
                ]
            }
        }
    }

    result = parse_law_body(raw_detail)
    article = result["articles"][0]

    assert article["article_no"] == "43"
    assert article["article_no_display"] == "제43조의2"
    assert article["article_no_main"] == "43"
    assert article["article_no_branch"] == "2"
    assert article["article_key"] == "43-2"


def test_parse_law_body_classifies_appendix_content():
    raw_detail = {
        "법령": {
            "별표": [
                {
                    "별표제목": "별표 1",
                    "별표내용": "일반 서술형 별표 본문",
                },
                {
                    "별표제목": "별표이미지파일명",
                    "별표내용": "labor_card.jpg",
                },
                {
                    "별표제목": "별표",
                    "별표내용": "표 제목\n┌───┬───┐\n│A│B│\n└───┴───┘",
                },
            ]
        }
    }

    result = parse_law_body(raw_detail)
    appendices = result["appendices"]

    assert appendices[0]["content_category"] == "narrative"
    assert appendices[0]["is_searchable"] is True
    assert appendices[1]["content_category"] == "metadata"
    assert appendices[1]["is_searchable"] is False
    assert appendices[2]["content_category"] == "table_like"
    assert appendices[2]["is_searchable"] is False


def test_build_law_records_uses_article_key_and_skips_non_searchable_parts(tmp_path):
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
                    "article_no": "43",
                    "article_no_display": "제43조의2",
                    "article_no_main": "43",
                    "article_no_branch": "2",
                    "article_key": "43-2",
                    "article_title_raw": "체불사업주 명단 공개",
                    "article_title": "체불사업주 명단 공개",
                    "article_text_raw": "제43조의2(체불사업주 명단 공개) 본문",
                    "article_text": "제43조의2(체불사업주 명단 공개) 본문",
                    "paragraphs": [],
                }
            ],
            "supplementary": [
                {
                    "supplementary_title": "부칙",
                    "supplementary_text": "시행일 metadata",
                    "content_category": "metadata",
                    "is_searchable": False,
                }
            ],
            "appendices": [
                {
                    "appendix_title": "별표 1",
                    "appendix_text": "일반 별표 본문",
                    "content_category": "narrative",
                    "is_searchable": True,
                },
                {
                    "appendix_title": "별표이미지파일명",
                    "appendix_text": "labor_card.jpg",
                    "content_category": "metadata",
                    "is_searchable": False,
                },
                {
                    "appendix_title": "별표",
                    "appendix_text": "┌───┬───┐\n│A│B│\n└───┴───┘",
                    "content_category": "table_like",
                    "is_searchable": False,
                },
            ],
        },
    )

    records = build_law_records(
        normalized_base_dir=tmp_path / "normalized" / "01_current_law",
        max_chars=500,
        overlap=50,
        text_variant="best",
        preserve_structure=True,
    )

    article_records = [record for record in records if record["section_type"] == "article"]
    appendix_records = [record for record in records if record["section_type"] == "appendix"]
    supplementary_records = [record for record in records if record["section_type"] == "supplementary"]

    assert article_records[0]["id"] == "law::근로기준법::43-2::0"
    assert "조문번호: 제43조의2" in article_records[0]["text"]
    assert len(appendix_records) == 1
    assert appendix_records[0]["appendix_title"] == "별표 1"
    assert len(supplementary_records) == 0
