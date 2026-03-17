from src.parser.appendix_parser import parse_appendix_bundle


def test_parse_appendix_bundle_classifies_appendix_types_and_processing_policy():
    raw_detail = {
        "법령": {
            "기본정보": {
                "법령명_한글": "근로기준법 시행규칙",
                "법령ID": "001",
                "시행일자": "20250223",
                "법종구분": {"content": "부령"},
            },
            "별표": {
                "별표단위": [
                    {
                        "별표제목": "해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)",
                        "별표키": "000100E",
                        "별표구분": "별표",
                        "별표내용": [[
                            "1. 납품업체로부터 금품이나 향응을 제공받은 경우",
                            "2. 영업용 차량을 임의로 타인에게 대리운전하게 한 경우",
                        ]],
                        "별표PDF파일명": "law001.pdf",
                    },
                    {
                        "별표제목": "질환 분류표",
                        "별표키": "000200E",
                        "별표구분": "별표",
                        "별표내용": [[
                            "┌──────────┬──────────┐",
                            "│질환명     │질병코드  │",
                            "└──────────┴──────────┘",
                        ]],
                        "별표서식PDF파일링크": "/LSW/flDownload.do?flSeq=200",
                    },
                    {
                        "별표제목": "근로조건 위반 손해배상 청구 신청서",
                        "별표키": "000300F",
                        "별표구분": "서식",
                        "별표내용": [[
                            "접수번호 │ 처리기간: 30일",
                            "신청인 (서명 또는 인)",
                        ]],
                        "별표PDF파일명": "form001.pdf",
                    },
                    {
                        "별표제목": "삭제",
                        "별표키": "000400E",
                        "별표구분": "별표",
                        "별표내용": [],
                        "별표PDF파일명": "meta001.pdf",
                    },
                ]
            },
        }
    }

    bundle = parse_appendix_bundle(raw_detail)
    records = {record["appendix_key"]: record for record in bundle["appendix_records"]}

    assert bundle["law_name"] == "근로기준법 시행규칙"
    assert bundle["appendix_count"] == 4
    assert bundle["appendix_type_counts"]["appendix_document"] == 1
    assert bundle["appendix_type_counts"]["table_appendix"] == 1
    assert bundle["appendix_type_counts"]["form_appendix"] == 1
    assert bundle["appendix_type_counts"]["metadata_only"] == 1

    assert records["000100E"]["appendix_type"] == "appendix_document"
    assert records["000100E"]["is_default_serving_candidate"] is True
    assert records["000100E"]["processing_policy"]["recommended_next_step"] == "use_api_text_clean_as_primary"

    assert records["000200E"]["appendix_type"] == "table_appendix"
    assert records["000200E"]["processing_policy"]["pdf_fallback"] is True
    assert "reextract_pdf" in records["000200E"]["processing_policy"]["recommended_next_step"]

    assert records["000300F"]["appendix_type"] == "form_appendix"
    assert records["000300F"]["download_assets"]["pdf_file_name"] == "form001.pdf"

    assert records["000400E"]["appendix_type"] == "metadata_only"
    assert records["000400E"]["has_substantive_text"] is False


def test_parse_appendix_bundle_preserves_api_text_lines():
    raw_detail = {
        "법령": {
            "기본정보": {
                "법령명_한글": "근로기준법",
                "법령ID": "001",
            },
            "별표": {
                "별표단위": {
                    "별표제목": "해고 예고의 예외가 되는 근로자의 귀책사유",
                    "별표키": "000100E",
                    "별표구분": "별표",
                    "별표내용": [[
                        "1. 첫째 줄",
                        "2. 둘째 줄",
                    ]],
                }
            },
        }
    }

    bundle = parse_appendix_bundle(raw_detail)
    record = bundle["appendix_records"][0]

    assert record["api_text_raw"] == "1. 첫째 줄\n2. 둘째 줄"
    assert record["api_text"] == "1. 첫째 줄 2. 둘째 줄"
    assert record["api_text_lines"] == ["1. 첫째 줄", "2. 둘째 줄"]
