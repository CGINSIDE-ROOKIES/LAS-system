from src.parser.law_reference_parser import parse_law_article_references


FAMILY_LAWS = [
    {"law_name": "근로기준법", "classified_level": "법", "kind_name": "법률"},
    {"law_name": "근로기준법 시행령", "classified_level": "시행령", "kind_name": "대통령령"},
    {"law_name": "근로기준법 시행규칙", "classified_level": "시행규칙", "kind_name": "고용노동부령"},
]

ARTICLE_ORDER = [
    {"article_key": "2", "article_no_display": "제2조"},
    {"article_key": "3", "article_no_display": "제3조"},
    {"article_key": "4", "article_no_display": "제4조"},
    {"article_key": "5", "article_no_display": "제5조"},
]


def test_parse_law_article_references_resolves_same_law_and_relative_refs():
    refs = parse_law_article_references(
        "전조 및 제5조에 따른다.",
        source_law_name="근로기준법",
        source_law_level="법",
        source_article_key="4",
        article_order=ARTICLE_ORDER,
        root_law_name="근로기준법",
        family_laws=FAMILY_LAWS,
    )

    by_type = {ref["reference_type"]: ref for ref in refs}
    assert by_type["previous_article"]["target_law_name"] == "근로기준법"
    assert by_type["previous_article"]["target_article_keys"] == ["3"]
    assert by_type["same_law_article"]["target_article_keys"] == ["5"]


def test_parse_law_article_references_resolves_relative_scope_and_ranges():
    refs = parse_law_article_references(
        "이 영 제11조 및 제3조부터 제5조까지를 따른다.",
        source_law_name="근로기준법 시행규칙",
        source_law_level="시행규칙",
        source_article_key="4",
        article_order=ARTICLE_ORDER,
        root_law_name="근로기준법",
        family_laws=FAMILY_LAWS,
    )

    relative_scope = next(ref for ref in refs if ref["reference_type"] == "relative_scope")
    same_law = next(ref for ref in refs if ref["reference_type"] == "same_law_article")

    assert relative_scope["target_law_name"] == "근로기준법 시행령"
    assert relative_scope["target_article_keys"] == ["11"]
    assert same_law["target_article_keys"] == ["3", "4", "5"]


def test_parse_law_article_references_marks_external_law_refs_unresolved():
    refs = parse_law_article_references(
        "민법 제750조에 따른 손해배상을 청구한다.",
        source_law_name="근로기준법",
        source_law_level="법",
        source_article_key="4",
        article_order=ARTICLE_ORDER,
        root_law_name="근로기준법",
        family_laws=FAMILY_LAWS,
    )

    assert len(refs) == 1
    ref = refs[0]
    assert ref["target_law_name"] == "민법"
    assert ref["target_article_keys"] == ["750"]
    assert ref["resolution_status"] == "unresolved_external"
