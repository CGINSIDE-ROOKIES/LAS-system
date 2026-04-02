from src.common.io_utils import _write_json, write_jsonl
from src.export.law_graph_exporter import build_law_graph_export_rows, write_law_graph_export


def test_build_law_graph_export_rows_dedupes_article_nodes_and_splits_edges(tmp_path):
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
                "source_file_path": "a.json",
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
                "text": "더 긴 본문 텍스트",
                "display_text": "더 긴 본문",
                "source_file_path": "a.json",
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
                "source_file_path": "a.json",
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
                "source_file_path": "b.json",
            },
        ],
        corpus_path,
    )

    write_jsonl(
        [
            {
                "id": "relation::law::001::001::10",
                "relation_model": "law_to_law",
                "relation_type": "related_law",
                "relation_types": ["related_law", "same_law_reference"],
                "resolution_status": "resolved",
                "relation_confidence": 0.95,
                "source_law_uid": "001",
                "law_uid": "001",
                "source_article_key": "10",
                "source_article_no_display": "제10조",
                "article_keys": ["10", "7"],
                "reference_texts": ["제10조", "제7조"],
            },
            {
                "id": "relation::law::002::001::1",
                "relation_model": "law_to_law",
                "relation_type": "cited_law",
                "relation_types": ["cited_law"],
                "resolution_status": "resolved",
                "relation_confidence": 0.8,
                "source_law_uid": "002",
                "law_uid": "001",
                "source_article_key": "1",
                "source_article_no_display": "제1조",
                "article_keys": [],
                "reference_texts": ["근로기준법"],
            },
            {
                "id": "relation::law::002::external::x::1",
                "relation_model": "law_to_law",
                "relation_type": "related_law",
                "relation_types": ["related_law", "external_reference"],
                "resolution_status": "unresolved_external",
                "relation_confidence": 0.45,
                "source_law_uid": "002",
                "law_uid": None,
                "source_article_key": "1",
                "article_keys": ["99"],
                "reference_texts": ["외부 법령 제99조"],
            },
        ],
        relations_path,
    )

    rows = build_law_graph_export_rows(
        legal_corpus_path=corpus_path,
        legal_relations_path=relations_path,
    )

    assert len(rows["law_nodes"]) == 2
    assert len(rows["article_nodes"]) == 3
    assert len(rows["has_article_edges"]) == 3
    assert len(rows["has_child_law_edges"]) == 1
    assert len(rows["refers_to_law_edges"]) == 1
    assert len(rows["refers_to_article_edges"]) == 1

    article = next(row for row in rows["article_nodes"] if row["article_uid"] == "article::001::10")
    assert article["text"] == "더 긴 본문 텍스트"

    edge = rows["refers_to_article_edges"][0]
    assert edge["source_article_uid"] == "article::001::10"
    assert edge["target_article_uid"] == "article::001::7"

    hierarchy_edge = rows["has_child_law_edges"][0]
    assert hierarchy_edge["source_law_uid"] == "001"
    assert hierarchy_edge["target_law_uid"] == "002"


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
    assert all(row["law_uid"] != "unknown-law" for row in rows["law_nodes"])
    assert all(row["law_uid"] != "unknown-law" for row in rows["article_nodes"])

    child = next(row for row in rows["law_nodes"] if row["law_uid"] == "003140")
    assert child["root_law_name"] == "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"

    child_article = next(row for row in rows["article_nodes"] if row["law_uid"] == "003140")
    assert child_article["root_law_name"] == "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률"


def test_build_law_graph_export_rows_builds_family_hierarchy(tmp_path):
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
            "edge_id": "HAS_CHILD_LAW::002::003",
            "edge_type": "HAS_CHILD_LAW",
            "source_law_uid": "002",
            "target_law_uid": "003",
            "root_law_uid": "001",
            "root_law_name": "근로기준법",
        },
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
    assert manifest["has_child_law_edge_count"] == 0
    assert (output_dir / "graph_law_nodes.jsonl").exists()
    assert (output_dir / "graph_article_nodes.jsonl").exists()
    assert (output_dir / "graph_edges_has_child_law.jsonl").exists()
    assert (output_dir / "graph_manifest.json").exists()
