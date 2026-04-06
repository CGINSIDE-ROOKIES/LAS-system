from src.common.io_utils import write_jsonl
from src.export.law_graph_neo4j_seed import (
    ARTICLE_NODE_QUERY,
    DELEGATES_TO_LAW_QUERY,
    HAS_ARTICLE_QUERY,
    HAS_CHILD_LAW_QUERY,
    LAW_NODE_QUERY,
    REFERS_TO_ARTICLE_QUERY,
    REFERS_TO_LAW_QUERY,
    build_seed_manifest,
    iter_seed_operations,
    load_graph_seed_rows,
)


def test_load_graph_seed_rows_and_manifest(tmp_path):
    base_dir = tmp_path / "graph"
    write_jsonl([{"law_uid": "001"}], base_dir / "graph_law_nodes.jsonl")
    write_jsonl([{"article_uid": "article::001::1"}], base_dir / "graph_article_nodes.jsonl")
    write_jsonl([{"edge_id": "HAS_ARTICLE::001::article::001::1"}], base_dir / "graph_edges_has_article.jsonl")
    write_jsonl([{"edge_id": "HAS_CHILD_LAW::001::002"}], base_dir / "graph_edges_has_child_law.jsonl")
    write_jsonl([{"edge_id": "DELEGATES_TO_LAW::001::002"}], base_dir / "graph_edges_delegates_to_law.jsonl")
    write_jsonl([{"edge_id": "REFERS_TO_LAW::001::002"}], base_dir / "graph_edges_refers_to_law.jsonl")
    write_jsonl([{"edge_id": "REFERS_TO_ARTICLE::article::001::1::article::002::2"}], base_dir / "graph_edges_refers_to_article.jsonl")

    rows = load_graph_seed_rows(base_dir)
    manifest = build_seed_manifest(rows)

    assert manifest == {
        "law_node_count": 1,
        "article_node_count": 1,
        "has_article_edge_count": 1,
        "has_child_law_edge_count": 1,
        "delegates_to_law_edge_count": 1,
        "refers_to_law_edge_count": 1,
        "refers_to_article_edge_count": 1,
    }


def test_iter_seed_operations_returns_expected_query_order():
    rows = {
        "law_nodes": [{"law_uid": "001"}],
        "article_nodes": [{"article_uid": "article::001::1"}],
        "has_article_edges": [{"edge_id": "HAS_ARTICLE::001::article::001::1"}],
        "has_child_law_edges": [{"edge_id": "HAS_CHILD_LAW::001::002"}],
        "delegates_to_law_edges": [{"edge_id": "DELEGATES_TO_LAW::001::002"}],
        "refers_to_law_edges": [{"edge_id": "REFERS_TO_LAW::001::002"}],
        "refers_to_article_edges": [{"edge_id": "REFERS_TO_ARTICLE::article::001::1::article::002::2"}],
    }

    operations = iter_seed_operations(rows)
    assert [query for query, _ in operations] == [
        LAW_NODE_QUERY,
        ARTICLE_NODE_QUERY,
        HAS_ARTICLE_QUERY,
        HAS_CHILD_LAW_QUERY,
        DELEGATES_TO_LAW_QUERY,
        REFERS_TO_LAW_QUERY,
        REFERS_TO_ARTICLE_QUERY,
    ]
