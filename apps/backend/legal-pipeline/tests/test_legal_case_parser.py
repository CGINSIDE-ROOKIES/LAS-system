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


def test_case_number_reference_extraction_does_not_treat_amounts_as_case_numbers():
    text = "피고는 119만2666원과 66만4000원을 지급하였고, 근로기준법 제43조의2를 함께 언급하였다."

    refs = extract_case_number_refs(text)

    assert refs == []


def test_article_reference_extraction_supports_multiple_articles_with_mixed_notation():
    text = "이 사건은 근로기준법 제23조, 30조 및 제43조의2의 적용 여부가 문제된다."

    article_refs = extract_explicit_article_refs(text, ["근로기준법", "최저임금법"])

    assert article_refs["근로기준법"] == [
        {"article_key": "23", "article_no_display": "제23조"},
        {"article_key": "30", "article_no_display": "제30조"},
        {"article_key": "43-2", "article_no_display": "제43조의2"},
    ]



def test_case_number_reference_extraction_does_not_treat_articles_as_case_numbers():
    text = "원심은 근로기준법 제43조의2 및 제12조를 근거로 판단하였다."

    refs = extract_case_number_refs(text)

    assert refs == []
