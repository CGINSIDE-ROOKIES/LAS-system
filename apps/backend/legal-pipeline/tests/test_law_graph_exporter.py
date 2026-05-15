from src.common.io_utils import write_jsonl
from src.export.law_graph_exporter import build_law_graph_export_rows, write_law_graph_export


def test_build_law_graph_export_rows_dedupes_article_nodes_and_builds_reference_edges_from_corpus(tmp_path):
    corpus_path = tmp_path / "dataset" / "legal_corpus.jsonl"
    relations_path = tmp_path / "dataset" / "legal_relations.jsonl"

    write_jsonl(
        [
            {
                "id": "law::001::article::10::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "ef_yd": "20250101",
                "law_id": "001",
                "mst": "100",
                "article_key": "10",
                "article_no_display": "제10조",
                "text": "짧은 본문",
                "display_text": "짧은 본문",
                "source_file_path": "root.json",
            },
            {
                "id": "law::001::article::10::1",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "ef_yd": "20250101",
                "law_id": "001",
                "mst": "100",
                "article_key": "10",
                "article_no_display": "제10조",
                "text": "제7조 및 근로기준법 시행령에 따른다.",
                "display_text": "제7조 및 근로기준법 시행령에 따른다.",
                "source_file_path": "root.json",
            },
            {
                "id": "law::001::article::7::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "7",
                "article_no_display": "제7조",
                "text": "제7조 본문",
                "display_text": "제7조 본문",
                "source_file_path": "root.json",
            },
            {
                "id": "law::002::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "002",
                "law_name": "근로기준법 시행령",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "시행령",
                "kind_name": "대통령령",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "시행령 본문",
                "display_text": "시행령 본문",
                "source_file_path": "decree.json",
            },
        ],
        corpus_path,
    )
    write_jsonl([], relations_path)

    rows = build_law_graph_export_rows(
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert len(rows["law_nodes"]) == 2
    assert len(rows["article_nodes"]) == 3
    assert len(rows["has_article_edges"]) == 3
    assert len(rows["has_child_law_edges"]) == 1
    assert len(rows["delegates_to_law_edges"]) == 0
    assert len(rows["refers_to_law_edges"]) == 1
    assert len(rows["refers_to_article_edges"]) == 1

    article = next(row for row in rows["article_nodes"] if row["article_uid"] == "article::001::10")
    assert article["text"] == "제7조 및 근로기준법 시행령에 따른다."

    article_edge = rows["refers_to_article_edges"][0]
    assert article_edge["source_article_uid"] == "article::001::10"
    assert article_edge["target_article_uid"] == "article::001::7"

    law_edge = rows["refers_to_law_edges"][0]
    assert law_edge["source_law_uid"] == "001"
    assert law_edge["target_law_uid"] == "002"
    assert "explicit_law_name" in law_edge["relation_types"]


def test_build_law_graph_export_rows_builds_case_nodes_and_case_relation_edges(tmp_path):
    corpus_path = tmp_path / "dataset" / "legal_corpus.jsonl"
    relations_path = tmp_path / "dataset" / "legal_relations.jsonl"

    write_jsonl(
        [
            {
                "id": "law::001::article::6::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "최저임금법",
                "root_law_uid": "001",
                "root_law_name": "최저임금법",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "6",
                "article_no_display": "제6조",
                "text": "최저임금 조문",
                "display_text": "최저임금 조문",
                "source_file_path": "law.json",
            },
            {
                "id": "case_chunk::case::detc::180923::0",
                "canonical_case_id": "case::detc::180923",
                "canonical_id": "case::detc::180923",
                "doc_type": "detc",
                "doc_type_label": "헌재결정례",
                "title": "최저임금법 제6조 제5항 위헌소원",
                "doc_number": "2020헌바11",
                "decision_date": "20230525",
                "doc_id": "180923",
                "detail_link": "/DRF/lawService.do?target=detc&ID=180923",
                "source_file_path": "case.json",
                "chunk_index": 0,
                "text": "첫 청크",
            },
            {
                "id": "case_chunk::case::detc::180923::1",
                "canonical_case_id": "case::detc::180923",
                "canonical_id": "case::detc::180923",
                "doc_type": "detc",
                "doc_type_label": "헌재결정례",
                "chunk_index": 1,
                "text": "둘째 청크",
            },
        ],
        corpus_path,
    )
    write_jsonl(
        [
            {
                "id": "relation::case::detc::180923::001",
                "canonical_case_id": "case::detc::180923",
                "canonical_id": "case::detc::180923",
                "relation_model": "law_to_case",
                "relation_type": "related_law",
                "relation_types": ["search_hit", "related_law"],
                "relation_confidence": 0.98,
                "resolution_status": "resolved",
                "doc_type": "relation",
                "doc_type_label": "헌재결정례",
                "target": "detc",
                "title": "최저임금법 제6조 제5항 위헌소원",
                "doc_number": "2020헌바11",
                "law_uid": "001",
                "law_name": "최저임금법",
                "article_keys": ["6"],
                "article_no_displays": ["제6조"],
                "subject_article_keys": ["6"],
                "subject_article_no_displays": ["제6조"],
                "subject_article_reference_sources": ["structured_subject_field"],
                "source_group": "03_expanded_related_docs",
                "source_file_path": "relation.json",
            },
            {
                "id": "case_relation::case::detc::180923::case::prec::1",
                "canonical_case_id": "case::detc::180923",
                "source_canonical_case_id": "case::detc::180923",
                "target_canonical_case_id": "case::prec::1",
                "relation_model": "case_to_case",
                "relation_type": "cited_case",
                "relation_types": ["cited_case"],
                "relation_confidence": 0.95,
                "resolution_status": "resolved",
                "doc_type": "relation",
                "doc_type_label": "헌재결정례",
                "target": "detc",
                "title": "최저임금법 제6조 제5항 위헌소원",
                "doc_number": "2020헌바11",
                "target_target": "prec",
                "target_doc_type_label": "판례",
                "target_title": "임금",
                "target_doc_number": "2016다2451",
                "referenced_case_number": "2016다2451",
                "source_group": "04_case_to_case_relations",
            },
        ],
        relations_path,
    )

    rows = build_law_graph_export_rows(
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert [row["canonical_case_id"] for row in rows["case_nodes"]] == [
        "case::detc::180923",
        "case::prec::1",
    ]
    source_case = rows["case_nodes"][0]
    assert source_case["doc_type"] == "detc"
    assert source_case["title"] == "최저임금법 제6조 제5항 위헌소원"

    assert len(rows["case_related_to_law_edges"]) == 1
    law_edge = rows["case_related_to_law_edges"][0]
    assert law_edge["source_canonical_case_id"] == "case::detc::180923"
    assert law_edge["target_law_uid"] == "001"

    assert len(rows["case_related_to_article_edges"]) == 1
    article_edge = rows["case_related_to_article_edges"][0]
    assert article_edge["target_article_uid"] == "article::001::6"

    assert len(rows["case_challenges_law_edges"]) == 1
    challenge_law_edge = rows["case_challenges_law_edges"][0]
    assert challenge_law_edge["edge_type"] == "CHALLENGES_LAW"
    assert challenge_law_edge["source_canonical_case_id"] == "case::detc::180923"
    assert challenge_law_edge["target_law_uid"] == "001"
    assert challenge_law_edge["subject_article_keys"] == ["6"]

    assert len(rows["case_challenges_article_edges"]) == 1
    challenge_article_edge = rows["case_challenges_article_edges"][0]
    assert challenge_article_edge["edge_type"] == "CHALLENGES_ARTICLE"
    assert challenge_article_edge["source_canonical_case_id"] == "case::detc::180923"
    assert challenge_article_edge["target_article_uid"] == "article::001::6"
    assert challenge_article_edge["reference_sources"] == ["structured_subject_field"]

    assert len(rows["case_cites_case_edges"]) == 1
    case_edge = rows["case_cites_case_edges"][0]
    assert case_edge["source_canonical_case_id"] == "case::detc::180923"
    assert case_edge["target_canonical_case_id"] == "case::prec::1"


def test_build_law_graph_export_rows_skips_blank_law_name_and_restores_root_law_name(tmp_path):
    corpus_path = tmp_path / "dataset" / "legal_corpus.jsonl"
    relations_path = tmp_path / "dataset" / "legal_relations.jsonl"

    write_jsonl(
        [
            {
                "id": "law::000130::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "000130",
                "law_name": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률",
                "root_law_uid": "000130",
                "root_law_name": "남녀고용평등과 일 가정 양립 지원에 관한 법률",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "본문",
                "display_text": "본문",
                "source_file_path": "root.json",
            },
            {
                "id": "law::003140::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "003140",
                "law_name": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령",
                "root_law_uid": "000130",
                "root_law_name": "남녀고용평등과 일 가정 양립 지원에 관한 법률",
                "classified_level": "시행령",
                "kind_name": "대통령령",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "시행령 본문",
                "display_text": "시행령 본문",
                "source_file_path": "child.json",
            },
            {
                "id": "law::unknown-law::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "unknown-law",
                "law_name": "",
                "root_law_uid": None,
                "root_law_name": "근로자퇴직급여 보장법",
                "classified_level": "기타",
                "kind_name": None,
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "이름 없는 본문",
                "display_text": "이름 없는 본문",
                "source_file_path": "unnamed.json",
            },
        ],
        corpus_path,
    )
    write_jsonl([], relations_path)

    rows = build_law_graph_export_rows(
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert len(rows["law_nodes"]) == 2
    assert len(rows["article_nodes"]) == 2
    assert len(rows["has_child_law_edges"]) == 1
    assert len(rows["delegates_to_law_edges"]) == 0
    assert all(row["law_uid"] != "unknown-law" for row in rows["law_nodes"])
    assert all(row["law_uid"] != "unknown-law" for row in rows["article_nodes"])

    child = next(row for row in rows["law_nodes"] if row["law_uid"] == "003140")
    assert child["root_law_name"] == "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"

    child_article = next(row for row in rows["article_nodes"] if row["law_uid"] == "003140")
    assert child_article["root_law_name"] == "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"


def test_build_law_graph_export_rows_builds_family_hierarchy_without_cross_branch_pairing(tmp_path):
    corpus_path = tmp_path / "dataset" / "legal_corpus.jsonl"
    relations_path = tmp_path / "dataset" / "legal_relations.jsonl"

    write_jsonl(
        [
            {
                "id": "law::001::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "본문",
                "display_text": "본문",
                "source_file_path": "law.json",
            },
            {
                "id": "law::002::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "002",
                "law_name": "근로기준법 시행령",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "시행령",
                "kind_name": "대통령령",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "본문",
                "display_text": "본문",
                "source_file_path": "decree.json",
            },
            {
                "id": "law::003::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "003",
                "law_name": "근로기준법 시행규칙",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "시행규칙",
                "kind_name": "고용노동부령",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "본문",
                "display_text": "본문",
                "source_file_path": "rule.json",
            },
            {
                "id": "law::004::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "004",
                "law_name": "근로감독관규정",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "기타",
                "kind_name": "고시",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "본문",
                "display_text": "본문",
                "source_file_path": "other.json",
            },
            {
                "id": "law::005::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "005",
                "law_name": "근로감독관증 규칙",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "기타",
                "kind_name": "규칙",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "본문",
                "display_text": "본문",
                "source_file_path": "other-rule.json",
            },
        ],
        corpus_path,
    )
    write_jsonl([], relations_path)

    rows = build_law_graph_export_rows(
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert rows["has_child_law_edges"] == [
        {
            "edge_id": "HAS_CHILD_LAW::001::002",
            "edge_type": "HAS_CHILD_LAW",
            "source_law_uid": "001",
            "target_law_uid": "002",
            "root_law_uid": "001",
            "root_law_name": "근로기준법",
        },
        {
            "edge_id": "HAS_CHILD_LAW::001::004",
            "edge_type": "HAS_CHILD_LAW",
            "source_law_uid": "001",
            "target_law_uid": "004",
            "root_law_uid": "001",
            "root_law_name": "근로기준법",
        },
        {
            "edge_id": "HAS_CHILD_LAW::001::005",
            "edge_type": "HAS_CHILD_LAW",
            "source_law_uid": "001",
            "target_law_uid": "005",
            "root_law_uid": "001",
            "root_law_name": "근로기준법",
        },
        {
            "edge_id": "HAS_CHILD_LAW::002::003",
            "edge_type": "HAS_CHILD_LAW",
            "source_law_uid": "002",
            "target_law_uid": "003",
            "root_law_uid": "001",
            "root_law_name": "근로기준법",
        },
    ]


def test_build_law_graph_export_rows_builds_delegation_edges_with_branch_matching(tmp_path):
    corpus_path = tmp_path / "dataset" / "legal_corpus.jsonl"
    relations_path = tmp_path / "dataset" / "legal_relations.jsonl"

    write_jsonl(
        [
            {
                "id": "law::001::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "대통령령으로 정한다.",
                "display_text": "대통령령으로 정한다.",
                "source_file_path": "law.json",
            },
            {
                "id": "law::002::article::2::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "002",
                "law_name": "근로기준법 시행령",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "시행령",
                "kind_name": "대통령령",
                "article_key": "2",
                "article_no_display": "제2조",
                "text": "고용노동부령으로 정한다.",
                "display_text": "고용노동부령으로 정한다.",
                "source_file_path": "decree.json",
            },
            {
                "id": "law::003::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "003",
                "law_name": "근로기준법 시행규칙",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "시행규칙",
                "kind_name": "고용노동부령",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "시행규칙 본문",
                "display_text": "시행규칙 본문",
                "source_file_path": "rule.json",
            },
            {
                "id": "law::004::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "004",
                "law_name": "근로감독관증 규칙",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "기타",
                "kind_name": "규칙",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "다른 규칙 본문",
                "display_text": "다른 규칙 본문",
                "source_file_path": "other-rule.json",
            },
        ],
        corpus_path,
    )
    write_jsonl([], relations_path)

    rows = build_law_graph_export_rows(
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert rows["delegates_to_law_edges"] == [
        {
            "edge_id": "DELEGATES_TO_LAW::001::002",
            "edge_type": "DELEGATES_TO_LAW",
            "source_law_uid": "001",
            "target_law_uid": "002",
            "root_law_uid": "001",
            "root_law_name": "근로기준법",
            "relation_type": "presidential_decree",
            "relation_types": ["presidential_decree", "delegation"],
            "relation_confidence": 0.9,
            "source_article_keys": ["1"],
            "source_article_no_displays": ["제1조"],
            "reference_texts": ["제1조"],
        },
        {
            "edge_id": "DELEGATES_TO_LAW::002::003",
            "edge_type": "DELEGATES_TO_LAW",
            "source_law_uid": "002",
            "target_law_uid": "003",
            "root_law_uid": "001",
            "root_law_name": "근로기준법",
            "relation_type": "ministerial_rule",
            "relation_types": ["ministerial_rule", "delegation"],
            "relation_confidence": 0.9,
            "source_article_keys": ["2"],
            "source_article_no_displays": ["제2조"],
            "reference_texts": ["제2조"],
        },
    ]


def test_build_law_graph_export_rows_uses_corpus_article_refs_and_preserves_paragraph_metadata(tmp_path):
    corpus_path = tmp_path / "dataset" / "legal_corpus.jsonl"
    relations_path = tmp_path / "dataset" / "legal_relations.jsonl"

    write_jsonl(
        [
            {
                "id": "law::001::article::7::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "7",
                "article_no_display": "제7조",
                "text": "제7조 본문",
                "display_text": "제7조 본문",
                "source_file_path": "law.json",
            },
            {
                "id": "law::001::article::10::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "10",
                "article_no_display": "제10조",
                "text": "같은 법 제7조제3항에 따른다.",
                "display_text": "같은 법 제7조제3항에 따른다.",
                "source_file_path": "law.json",
            },
        ],
        corpus_path,
    )
    write_jsonl([], relations_path)

    rows = build_law_graph_export_rows(
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert rows["refers_to_law_edges"] == []
    assert rows["refers_to_article_edges"] == [
        {
            "edge_id": "REFERS_TO_ARTICLE::article::001::10::article::001::7",
            "edge_type": "REFERS_TO_ARTICLE",
            "source_article_uid": "article::001::10",
            "target_article_uid": "article::001::7",
            "source_law_uid": "001",
            "target_law_uid": "001",
            "source_article_key": "10",
            "source_article_no_display": "제10조",
            "target_article_key": "7",
            "target_article_no_display": "제7조",
            "relation_type": "related_law",
            "relation_types": ["related_law", "relative_scope", "same_law_reference", "relative_reference"],
            "resolution_status": "resolved",
            "relation_confidence": 0.9,
            "target_paragraph_nos": ["3"],
            "target_item_nos": [],
            "target_subitem_nos": [],
            "reference_texts": ["같은 법 제7조제3항"],
        }
    ]


def test_build_law_graph_export_rows_falls_back_to_law_edge_when_target_article_is_missing(tmp_path):
    corpus_path = tmp_path / "dataset" / "legal_corpus.jsonl"
    relations_path = tmp_path / "dataset" / "legal_relations.jsonl"

    write_jsonl(
        [
            {
                "id": "law::001::article::10::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "10",
                "article_no_display": "제10조",
                "text": "근로기준법 시행령 제99조제2항에 따른다.",
                "display_text": "근로기준법 시행령 제99조제2항에 따른다.",
                "source_file_path": "law.json",
            },
            {
                "id": "law::002::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "002",
                "law_name": "근로기준법 시행령",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "시행령",
                "kind_name": "대통령령",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "시행령 본문",
                "display_text": "시행령 본문",
                "source_file_path": "decree.json",
            },
        ],
        corpus_path,
    )
    write_jsonl([], relations_path)

    rows = build_law_graph_export_rows(
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert rows["refers_to_article_edges"] == []
    assert rows["refers_to_law_edges"] == [
        {
            "edge_id": "REFERS_TO_LAW::001::002",
            "edge_type": "REFERS_TO_LAW",
            "source_law_uid": "001",
            "target_law_uid": "002",
            "root_law_uid": "001",
            "root_law_name": "근로기준법",
            "relation_type": "cited_law",
            "relation_types": ["cited_law", "explicit_law_article"],
            "resolution_status": "resolved",
            "relation_confidence": 0.95,
            "source_article_keys": ["10"],
            "source_article_no_displays": ["제10조"],
            "target_article_keys": ["99"],
            "target_article_no_displays": ["제99조"],
            "target_paragraph_nos": ["2"],
            "target_item_nos": [],
            "target_subitem_nos": [],
            "reference_texts": ["근로기준법 시행령 제99조제2항"],
        }
    ]


def test_write_law_graph_export_writes_manifest_and_files(tmp_path):
    corpus_path = tmp_path / "dataset" / "legal_corpus.jsonl"
    relations_path = tmp_path / "dataset" / "legal_relations.jsonl"
    output_dir = tmp_path / "handoff"

    write_jsonl(
        [
            {
                "id": "law::001::article::1::0",
                "doc_type": "law",
                "section_type": "article",
                "law_uid": "001",
                "law_name": "근로기준법",
                "root_law_uid": "001",
                "root_law_name": "근로기준법",
                "classified_level": "법",
                "kind_name": "법률",
                "article_key": "1",
                "article_no_display": "제1조",
                "text": "본문",
                "display_text": "본문",
                "source_file_path": "a.json",
            }
        ],
        corpus_path,
    )
    write_jsonl([], relations_path)

    manifest = write_law_graph_export(
        output_dir,
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert manifest["law_node_count"] == 1
    assert manifest["article_node_count"] == 1
    assert manifest["case_node_count"] == 0
    assert manifest["has_child_law_edge_count"] == 0
    assert manifest["delegates_to_law_edge_count"] == 0
    assert manifest["case_related_to_law_edge_count"] == 0
    assert manifest["case_related_to_article_edge_count"] == 0
    assert manifest["case_cites_case_edge_count"] == 0
    assert (output_dir / "graph_law_nodes.jsonl").exists()
    assert (output_dir / "graph_article_nodes.jsonl").exists()
    assert (output_dir / "graph_case_nodes.jsonl").exists()
    assert (output_dir / "graph_edges_has_child_law.jsonl").exists()
    assert (output_dir / "graph_edges_delegates_to_law.jsonl").exists()
    assert (output_dir / "graph_edges_case_related_to_law.jsonl").exists()
    assert (output_dir / "graph_edges_case_related_to_article.jsonl").exists()
    assert (output_dir / "graph_edges_case_cites_case.jsonl").exists()
    assert (output_dir / "graph_manifest.json").exists()
