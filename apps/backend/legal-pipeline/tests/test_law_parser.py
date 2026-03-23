from src.parser.law_parser import parse_law_body, parse_law_body_record


def test_parse_law_body_basic_article():
    raw_detail = {
        "법령": {
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "1",
                        "조문제목": "목적",
                        "조문내용": "이 법은 근로조건의 기준을 정함을 목적으로 한다.",
                    }
                ]
            }
        }
    }

    result = parse_law_body(raw_detail)

    assert "articles" in result
    assert len(result["articles"]) == 1
    assert result["articles"][0]["article_no"] == "1"
    assert result["articles"][0]["article_title"] == "목적"


def test_parse_law_body_record_basic():
    record = {
        "law_ref": {
            "law_id": "001",
            "law_name": "근로기준법",
        },
        "law_body": {
            "법령": {
                "조문": {
                    "조문단위": [
                        {
                            "조문번호": "1",
                            "조문제목": "목적",
                            "조문내용": "이 법은 근로조건의 기준을 정함을 목적으로 한다.",
                        }
                    ]
                }
            }
        },
    }

    result = parse_law_body_record(record)

    assert result["law_id"] == "001"
    assert result["law_name"] == "근로기준법"
    assert len(result["articles"]) == 1
    assert result["articles"][0]["article_no"] == "1"


def test_parse_law_body_includes_supplementary_and_appendix_policy():
    raw_detail = {
        "법령": {
            "법령명한글": "근로기준법",
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "1",
                        "조문제목": "목적",
                        "조문내용": "본문이다.",
                    }
                ]
            },
            "부칙": {
                "부칙단위": [
                    {
                        "부칙제목": "부칙",
                        "부칙내용": "이 법은 공포한 날부터 시행한다.",
                    }
                ]
            },
            "별표": [
                {
                    "별표제목": "별표 1",
                    "별표내용": "별표 본문",
                },
                {
                    "별표제목": "별지서식 1",
                    "별표내용": "제외되어야 함",
                },
            ],
        }
    }

    result = parse_law_body(
        raw_detail,
        include_parts=["별표"],
        exclude_parts=["별지서식"],
    )

    assert result["supplementary_count"] == 1
    assert result["appendices_count"] == 1
    assert result["appendices"][0]["appendix_title"] == "별표 1"
    assert len(result["excluded_parts"]) == 1
    assert result["excluded_parts"][0]["appendix_title"] == "별지서식 1"


def test_parse_law_body_preserves_raw_and_flat_text_fields():
    raw_detail = {
        "법령": {
            "조문": {
                "조문단위": [
                    {
                        "JO": "000100",
                        "조문번호": "제1조",
                        "조문제목": "목적",
                        "조문내용": "제1항 본문\n  제1항 단서",
                        "항": {
                            "항단위": [
                                {
                                    "항번호": "①",
                                    "항내용": "근로조건의 기준을 정한다.\n 근로자의 기본적 생활을 보장한다.",
                                }
                            ]
                        },
                    }
                ]
            }
        }
    }

    result = parse_law_body(raw_detail)
    article = result["articles"][0]
    paragraph = article["paragraphs"][0]

    assert article["jo_code"] == "000100"
    assert article["article_text_raw"] == "제1항 본문\n제1항 단서"
    assert article["article_text"] == "제1항 본문 제1항 단서"
    assert paragraph["paragraph_text_raw"] == "근로조건의 기준을 정한다.\n근로자의 기본적 생활을 보장한다."
    assert paragraph["paragraph_text"] == "근로조건의 기준을 정한다. 근로자의 기본적 생활을 보장한다."


def test_parse_law_body_keeps_article_no_separate_from_jo_code():
    raw_detail = {
        "법령": {
            "조문": {
                "조문단위": [
                    {
                        "조문번호": "제1조",
                        "조문제목": "목적",
                        "조문내용": "본문",
                    }
                ]
            }
        }
    }

    result = parse_law_body(raw_detail)
    article = result["articles"][0]

    assert article["jo_code"] is None
    assert article["article_no"] == "제1조"
