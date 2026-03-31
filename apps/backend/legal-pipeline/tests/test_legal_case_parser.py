import json
from pathlib import Path

from src.parser.legal_case_parser import (
    extract_case_number_refs,
    extract_explicit_article_refs,
    find_related_law_names,
    parse_case_payload,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "legal_case"



def test_parse_case_payload_from_prec_json_fixture():
    payload = json.loads((FIXTURE_DIR / "prec_detail.json").read_text(encoding="utf-8"))

    parsed = parse_case_payload("prec", payload)

    assert parsed["canonical_case_id"] == "case::prec::123456"
    assert parsed["title"] == "임금"
    assert parsed["doc_number"] == "2019다12345"
    assert parsed["decision_date"] == "2019.05.30"
    assert "근로기준법 제43조의2" in parsed["body_text"]
    assert parsed["structured_case_refs"] == [
        {
            "case_number": "2018다12345",
            "source": "structured_field",
            "field_name": "참조판례",
        }
    ]
    assert parsed["structured_article_refs"] == [
        {
            "law_name": "근로기준법",
            "article_key": "43-2",
            "article_no_display": "제43조의2",
            "source": "structured_field",
            "field_name": "참조조문",
        }
    ]


def test_parse_case_payload_from_expc_json_fixture():
    payload = json.loads((FIXTURE_DIR / "expc_detail.json").read_text(encoding="utf-8"))

    parsed = parse_case_payload("expc", payload)

    assert parsed["canonical_case_id"] == "case::expc::330471"
    assert parsed["title"] == "민원인 - 근로기준법 관련 질의"
    assert parsed["doc_number"] == "16-0305"
    assert parsed["decision_date"] == "2016.09.01"
    assert "근로기준법 제43조의2" in parsed["body_text"]
    assert "사업주의 의무를 해석한다." in parsed["body_text"]


def test_parse_case_payload_from_detc_json_fixture_uses_jongguk_date():
    payload = json.loads((FIXTURE_DIR / "detc_detail.json").read_text(encoding="utf-8"))

    parsed = parse_case_payload("detc", payload)

    assert parsed["canonical_case_id"] == "case::detc::58400"
    assert parsed["title"] == "참전유공자예우에관한법률 제6조 제1항 위헌확인"
    assert parsed["doc_number"] == "2002헌마522"
    assert parsed["decision_date"] == "2003.07.24"
    assert parsed["body_sections"][0]["label"] == "판시사항"
    assert parsed["body_sections"][-1]["label"] == "전문"


def test_parse_case_payload_from_expc_html_fixture_uses_fallback_meta():
    payload = json.loads((FIXTURE_DIR / "expc_detail_html.json").read_text(encoding="utf-8"))

    parsed = parse_case_payload(
        "expc",
        payload,
        fallback={
            "doc_id": "EXP001",
            "title": "체불사업주 명단 공개 해석",
            "doc_number": "20-0001",
            "detail_link": "https://example.test/expc/EXP001",
        },
    )

    assert parsed["canonical_case_id"] == "case::expc::EXP001"
    assert parsed["title"] == "체불사업주 명단 공개 해석"
    assert parsed["doc_number"] == "20-0001"
    assert "근로기준법 제43조의2" in parsed["body_text"]



def test_article_and_law_reference_extraction():
    text = "이 사건은 근로기준법 제43조의2의 적용 여부가 문제된다."

    matched_laws = find_related_law_names(text, ["근로기준법", "최저임금법"])
    article_refs = extract_explicit_article_refs(text, ["근로기준법", "최저임금법"])

    assert matched_laws == ["근로기준법"]
    assert article_refs["근로기준법"] == [
        {"article_key": "43-2", "article_no_display": "제43조의2"}
    ]


def test_case_number_reference_extraction_excludes_self_doc_number():
    text = "이 사건의 판단 과정에서 2018다12345 판결과 2020헌바12 결정을 함께 참조하였다. 이 사건 번호는 2019다12345이다."

    refs = extract_case_number_refs(text, exclude_numbers=["2019다12345"])

    assert refs == ["2018다12345", "2020헌바12"]


def test_case_number_reference_extraction_rejects_article_and_amount_text():
    text = "근로기준법 제43조의2와 119만2666원의 지급 여부를 본 뒤 2018다12345 판결을 참조하였다."

    refs = extract_case_number_refs(text)

    assert refs == ["2018다12345"]


def test_parse_case_payload_sanitizes_detail_link_oc_param():
    payload = {
        "판례": {
            "판례일련번호": "123456",
            "사건명": "임금",
            "사건번호": "2019다12345",
            "판례상세링크": "/DRF/lawService.do?OC=matrix2012&target=prec&ID=123456",
            "판례내용": "본문",
        }
    }

    parsed = parse_case_payload("prec", payload)

    assert parsed["detail_link"] == "/DRF/lawService.do?target=prec&ID=123456"


def test_parse_case_payload_sanitizes_inline_detail_link_from_body_text():
    payload = {
        "판례": {
            "판례일련번호": "123456",
            "사건명": "임금",
            "사건번호": "2019다12345",
            "판례상세링크": "/DRF/lawService.do?OC=matrix2012&target=prec&ID=123456",
            "판례내용": "본문 /DRF/lawService.do?OC=matrix2012&target=prec&ID=123456",
        }
    }

    parsed = parse_case_payload("prec", payload)

    assert "OC=" not in parsed["body_text"]
    assert "/DRF/lawService.do?target=prec&ID=123456" in parsed["body_text"]
