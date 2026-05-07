from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.io_utils import _iter_jsonl


def load_graph_seed_rows(
    base_dir: str | Path,
) -> dict[str, list[dict[str, Any]]]:
    base_dir = Path(base_dir)
    return {
        "law_nodes": list(_iter_jsonl(base_dir / "graph_law_nodes.jsonl")),
        "article_nodes": list(_iter_jsonl(base_dir / "graph_article_nodes.jsonl")),
        "case_nodes": list(_iter_jsonl(base_dir / "graph_case_nodes.jsonl")),
        "has_article_edges": list(_iter_jsonl(base_dir / "graph_edges_has_article.jsonl")),
        "has_child_law_edges": list(_iter_jsonl(base_dir / "graph_edges_has_child_law.jsonl")),
        "delegates_to_law_edges": list(_iter_jsonl(base_dir / "graph_edges_delegates_to_law.jsonl")),
        "refers_to_law_edges": list(_iter_jsonl(base_dir / "graph_edges_refers_to_law.jsonl")),
        "refers_to_article_edges": list(_iter_jsonl(base_dir / "graph_edges_refers_to_article.jsonl")),
        "case_related_to_law_edges": list(_iter_jsonl(base_dir / "graph_edges_case_related_to_law.jsonl")),
        "case_related_to_article_edges": list(_iter_jsonl(base_dir / "graph_edges_case_related_to_article.jsonl")),
        "case_cites_case_edges": list(_iter_jsonl(base_dir / "graph_edges_case_cites_case.jsonl")),
    }


def build_seed_manifest(rows: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {
        "law_node_count": len(rows["law_nodes"]),
        "article_node_count": len(rows["article_nodes"]),
        "case_node_count": len(rows["case_nodes"]),
        "has_article_edge_count": len(rows["has_article_edges"]),
        "has_child_law_edge_count": len(rows["has_child_law_edges"]),
        "delegates_to_law_edge_count": len(rows["delegates_to_law_edges"]),
        "refers_to_law_edge_count": len(rows["refers_to_law_edges"]),
        "refers_to_article_edge_count": len(rows["refers_to_article_edges"]),
        "case_related_to_law_edge_count": len(rows["case_related_to_law_edges"]),
        "case_related_to_article_edge_count": len(rows["case_related_to_article_edges"]),
        "case_cites_case_edge_count": len(rows["case_cites_case_edges"]),
    }


LAW_NODE_QUERY = """
UNWIND $rows AS row
MERGE (n:Law {law_uid: row.law_uid})
SET n += row
""".strip()

ARTICLE_NODE_QUERY = """
UNWIND $rows AS row
MERGE (n:Article {article_uid: row.article_uid})
SET n += row
""".strip()

CASE_NODE_QUERY = """
UNWIND $rows AS row
MERGE (n:Case {canonical_case_id: row.canonical_case_id})
SET n += row
""".strip()

HAS_ARTICLE_QUERY = """
UNWIND $rows AS row
MATCH (law:Law {law_uid: row.source_law_uid})
MATCH (article:Article {article_uid: row.target_article_uid})
MERGE (law)-[r:HAS_ARTICLE {edge_id: row.edge_id}]->(article)
SET r += row
""".strip()

HAS_CHILD_LAW_QUERY = """
UNWIND $rows AS row
MATCH (source:Law {law_uid: row.source_law_uid})
MATCH (target:Law {law_uid: row.target_law_uid})
MERGE (source)-[r:HAS_CHILD_LAW {edge_id: row.edge_id}]->(target)
SET r += row
""".strip()

DELEGATES_TO_LAW_QUERY = """
UNWIND $rows AS row
MATCH (source:Law {law_uid: row.source_law_uid})
MATCH (target:Law {law_uid: row.target_law_uid})
MERGE (source)-[r:DELEGATES_TO_LAW {edge_id: row.edge_id}]->(target)
SET r += row
""".strip()

REFERS_TO_LAW_QUERY = """
UNWIND $rows AS row
MATCH (source:Law {law_uid: row.source_law_uid})
MATCH (target:Law {law_uid: row.target_law_uid})
MERGE (source)-[r:REFERS_TO_LAW {edge_id: row.edge_id}]->(target)
SET r += row
""".strip()

REFERS_TO_ARTICLE_QUERY = """
UNWIND $rows AS row
MATCH (source:Article {article_uid: row.source_article_uid})
MATCH (target:Article {article_uid: row.target_article_uid})
MERGE (source)-[r:REFERS_TO_ARTICLE {edge_id: row.edge_id}]->(target)
SET r += row
""".strip()

CASE_RELATED_TO_LAW_QUERY = """
UNWIND $rows AS row
MATCH (source:Case {canonical_case_id: row.source_canonical_case_id})
MATCH (target:Law {law_uid: row.target_law_uid})
MERGE (source)-[r:RELATED_TO_LAW {edge_id: row.edge_id}]->(target)
SET r += row
""".strip()

CASE_RELATED_TO_ARTICLE_QUERY = """
UNWIND $rows AS row
MATCH (source:Case {canonical_case_id: row.source_canonical_case_id})
MATCH (target:Article {article_uid: row.target_article_uid})
MERGE (source)-[r:RELATED_TO_ARTICLE {edge_id: row.edge_id}]->(target)
SET r += row
""".strip()

CASE_CITES_CASE_QUERY = """
UNWIND $rows AS row
MATCH (source:Case {canonical_case_id: row.source_canonical_case_id})
MATCH (target:Case {canonical_case_id: row.target_canonical_case_id})
MERGE (source)-[r:CITES_CASE {edge_id: row.edge_id}]->(target)
SET r += row
""".strip()


def iter_seed_operations(rows: dict[str, list[dict[str, Any]]]) -> list[tuple[str, list[dict[str, Any]]]]:
    return [
        (LAW_NODE_QUERY, rows["law_nodes"]),
        (ARTICLE_NODE_QUERY, rows["article_nodes"]),
        (CASE_NODE_QUERY, rows["case_nodes"]),
        (HAS_ARTICLE_QUERY, rows["has_article_edges"]),
        (HAS_CHILD_LAW_QUERY, rows["has_child_law_edges"]),
        (DELEGATES_TO_LAW_QUERY, rows["delegates_to_law_edges"]),
        (REFERS_TO_LAW_QUERY, rows["refers_to_law_edges"]),
        (REFERS_TO_ARTICLE_QUERY, rows["refers_to_article_edges"]),
        (CASE_RELATED_TO_LAW_QUERY, rows["case_related_to_law_edges"]),
        (CASE_RELATED_TO_ARTICLE_QUERY, rows["case_related_to_article_edges"]),
        (CASE_CITES_CASE_QUERY, rows["case_cites_case_edges"]),
    ]
