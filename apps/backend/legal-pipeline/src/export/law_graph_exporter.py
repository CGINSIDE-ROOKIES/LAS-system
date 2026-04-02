from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.io_utils import _iter_jsonl, _write_json, write_jsonl


def _article_uid(law_uid: str | None, article_key: str | None) -> str | None:
    law_uid = str(law_uid or "").strip()
    article_key = str(article_key or "").strip()
    if not law_uid or not article_key:
        return None
    return f"article::{law_uid}::{article_key}"


def _edge_id(prefix: str, source: str, target: str) -> str:
    return f"{prefix}::{source}::{target}"


def _clean_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _family_key(value: Any) -> str | None:
    text = _clean_str(value)
    if not text:
        return None
    return (
        text.replace("ㆍ", "")
        .replace("·", "")
        .replace(" ", "")
        .replace("_", "")
        .strip()
        .lower()
    ) or None


def _law_level_rank(classified_level: Any) -> int:
    level = _clean_str(classified_level)
    if level == "법":
        return 0
    if level == "시행령":
        return 1
    if level == "시행규칙":
        return 2
    return 3


def _build_has_child_law_edges(law_nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    families: dict[str, list[dict[str, Any]]] = {}
    for node in law_nodes.values():
        family_key = _family_key(node.get("root_law_name")) or _family_key(node.get("law_name"))
        if not family_key:
            continue
        families.setdefault(family_key, []).append(node)

    has_child_law_edges: dict[str, dict[str, Any]] = {}

    for _family_name_key, family_nodes in families.items():
        ordered_nodes = sorted(
            family_nodes,
            key=lambda row: (
                _law_level_rank(row.get("classified_level")),
                str(row.get("law_name") or ""),
                str(row.get("law_uid") or ""),
            ),
        )
        root_node = next((row for row in ordered_nodes if _clean_str(row.get("classified_level")) == "법"), None)
        if root_node is None:
            root_node = ordered_nodes[0] if ordered_nodes else None
        if root_node is None:
            continue

        root_law_uid = str(root_node.get("law_uid") or "").strip()
        if not root_law_uid:
            continue

        decree_node = next(
            (
                row
                for row in ordered_nodes
                if str(row.get("law_uid") or "").strip() != root_law_uid
                and _clean_str(row.get("classified_level")) == "시행령"
            ),
            None,
        )

        for node in ordered_nodes:
            law_uid = str(node.get("law_uid") or "").strip()
            if not law_uid or law_uid == root_law_uid:
                continue

            parent_law_uid = root_law_uid
            if (
                decree_node is not None
                and str(decree_node.get("law_uid") or "").strip() != law_uid
                and _clean_str(node.get("classified_level")) == "시행규칙"
            ):
                parent_law_uid = str(decree_node.get("law_uid") or "").strip()

            edge_key = _edge_id("HAS_CHILD_LAW", parent_law_uid, law_uid)
            has_child_law_edges.setdefault(
                edge_key,
                {
                    "edge_id": edge_key,
                    "edge_type": "HAS_CHILD_LAW",
                    "source_law_uid": parent_law_uid,
                    "target_law_uid": law_uid,
                    "root_law_uid": root_law_uid,
                    "root_law_name": _clean_str(root_node.get("law_name")),
                },
            )

    return sorted(has_child_law_edges.values(), key=lambda row: str(row.get("edge_id") or ""))


def build_law_graph_export_rows(
    *,
    legal_corpus_path: str | Path = "data/dataset/legal_corpus.jsonl",
    legal_relations_path: str | Path = "data/dataset/legal_relations.jsonl",
) -> dict[str, list[dict[str, Any]]]:
    legal_corpus_path = Path(legal_corpus_path)
    legal_relations_path = Path(legal_relations_path)

    law_nodes: dict[str, dict[str, Any]] = {}
    article_nodes: dict[str, dict[str, Any]] = {}
    has_article_edges: dict[str, dict[str, Any]] = {}
    has_child_law_edges: list[dict[str, Any]] = []
    refers_to_law_edges: dict[str, dict[str, Any]] = {}
    refers_to_article_edges: dict[str, dict[str, Any]] = {}

    for row in _iter_jsonl(legal_corpus_path):
        if str(row.get("doc_type") or "").strip() != "law":
            continue
        if str(row.get("section_type") or "").strip() != "article":
            continue

        law_uid = str(row.get("law_uid") or "").strip()
        law_name = _clean_str(row.get("law_name"))
        article_key = str(row.get("article_key") or "").strip()
        article_uid = _article_uid(law_uid, article_key)
        if not law_uid or not law_name or not article_uid:
            continue

        if law_uid not in law_nodes:
            law_nodes[law_uid] = {
                "node_type": "Law",
                "law_uid": law_uid,
                "law_name": law_name,
                "root_law_uid": row.get("root_law_uid"),
                "root_law_name": row.get("root_law_name"),
                "classified_level": row.get("classified_level"),
                "kind_name": row.get("kind_name"),
                "ef_yd": row.get("ef_yd"),
                "law_id": row.get("law_id"),
                "mst": row.get("mst"),
            }

        current_article = article_nodes.get(article_uid)
        candidate_text = str(row.get("text") or "")
        if current_article is None or len(candidate_text) > len(str(current_article.get("text") or "")):
            article_nodes[article_uid] = {
                "node_type": "Article",
                "article_uid": article_uid,
                "law_uid": law_uid,
                "root_law_uid": row.get("root_law_uid"),
                "law_name": law_name,
                "root_law_name": row.get("root_law_name"),
                "article_key": article_key,
                "article_no_display": row.get("article_no_display"),
                "text": row.get("text"),
                "display_text": row.get("display_text"),
                "source_file_path": row.get("source_file_path"),
            }

        edge_key = _edge_id("HAS_ARTICLE", law_uid, article_uid)
        has_article_edges.setdefault(
            edge_key,
            {
                "edge_id": edge_key,
                "edge_type": "HAS_ARTICLE",
                "source_law_uid": law_uid,
                "target_article_uid": article_uid,
            },
        )

    family_roots: dict[str, dict[str, Any]] = {}
    for node in sorted(
        law_nodes.values(),
        key=lambda row: (
            _family_key(row.get("root_law_name")) or _family_key(row.get("law_name")) or "",
            _law_level_rank(row.get("classified_level")),
            str(row.get("law_name") or ""),
        ),
    ):
        family_key = _family_key(node.get("root_law_name")) or _family_key(node.get("law_name"))
        if not family_key:
            continue
        current = family_roots.get(family_key)
        if current is None or _law_level_rank(node.get("classified_level")) < _law_level_rank(current.get("classified_level")):
            family_roots[family_key] = node

    for node in law_nodes.values():
        family_key = _family_key(node.get("root_law_name")) or _family_key(node.get("law_name"))
        family_root = family_roots.get(family_key) if family_key else None
        if family_root is not None:
            node["root_law_uid"] = family_root["law_uid"]
            node["root_law_name"] = family_root["law_name"]
        elif not _clean_str(node.get("root_law_name")):
            node["root_law_name"] = node["law_name"]

    for node in article_nodes.values():
        family_key = _family_key(node.get("root_law_name")) or _family_key(node.get("law_name"))
        family_root = family_roots.get(family_key) if family_key else None
        if family_root is not None:
            node["root_law_uid"] = family_root["law_uid"]
            node["root_law_name"] = family_root["law_name"]
        elif not _clean_str(node.get("root_law_name")):
            node["root_law_name"] = node["law_name"]

    has_child_law_edges = _build_has_child_law_edges(law_nodes)

    for row in _iter_jsonl(legal_relations_path):
        if str(row.get("relation_model") or "").strip() != "law_to_law":
            continue
        if str(row.get("resolution_status") or "").strip() == "unresolved_external":
            continue

        source_law_uid = str(row.get("source_law_uid") or "").strip()
        target_law_uid = str(row.get("law_uid") or "").strip()
        relation_type = str(row.get("relation_type") or "").strip()
        relation_types = list(row.get("relation_types") or [])
        source_article_key = str(row.get("source_article_key") or "").strip()
        source_article_uid = _article_uid(source_law_uid, source_article_key)

        if relation_type == "cited_law" and source_law_uid and target_law_uid:
            if source_law_uid not in law_nodes or target_law_uid not in law_nodes:
                continue
            edge_key = _edge_id("REFERS_TO_LAW", source_law_uid, target_law_uid)
            current = refers_to_law_edges.get(edge_key)
            if current is None:
                refers_to_law_edges[edge_key] = {
                    "edge_id": edge_key,
                    "edge_type": "REFERS_TO_LAW",
                    "source_law_uid": source_law_uid,
                    "target_law_uid": target_law_uid,
                    "relation_type": relation_type,
                    "relation_types": relation_types,
                    "resolution_status": row.get("resolution_status"),
                    "relation_confidence": row.get("relation_confidence"),
                    "reference_texts": list(row.get("reference_texts") or []),
                    "source_article_key": row.get("source_article_key"),
                    "source_article_no_display": row.get("source_article_no_display"),
                }
            else:
                current["relation_types"] = list(dict.fromkeys(list(current.get("relation_types") or []) + relation_types))
                current["reference_texts"] = list(
                    dict.fromkeys(list(current.get("reference_texts") or []) + list(row.get("reference_texts") or []))
                )
                current["relation_confidence"] = max(
                    float(current.get("relation_confidence") or 0),
                    float(row.get("relation_confidence") or 0),
                )

        if not source_article_uid or not target_law_uid:
            continue

        target_article_keys = [str(item).strip() for item in list(row.get("article_keys") or []) if str(item).strip()]
        if not target_article_keys:
            continue

        is_same_law = "same_law_reference" in relation_types and source_law_uid == target_law_uid
        filtered_target_article_keys = list(target_article_keys)
        if is_same_law:
            filtered_target_article_keys = [key for key in filtered_target_article_keys if key != source_article_key]
        if not filtered_target_article_keys:
            continue

        for target_article_key in filtered_target_article_keys:
            target_article_uid = _article_uid(target_law_uid, target_article_key)
            if not target_article_uid:
                continue
            if source_article_uid not in article_nodes or target_article_uid not in article_nodes:
                continue
            edge_key = _edge_id("REFERS_TO_ARTICLE", source_article_uid, target_article_uid)
            current = refers_to_article_edges.get(edge_key)
            if current is None:
                refers_to_article_edges[edge_key] = {
                    "edge_id": edge_key,
                    "edge_type": "REFERS_TO_ARTICLE",
                    "source_article_uid": source_article_uid,
                    "target_article_uid": target_article_uid,
                    "source_law_uid": source_law_uid,
                    "target_law_uid": target_law_uid,
                    "source_article_key": source_article_key,
                    "target_article_key": target_article_key,
                    "relation_type": relation_type,
                    "relation_types": relation_types,
                    "resolution_status": row.get("resolution_status"),
                    "relation_confidence": row.get("relation_confidence"),
                    "reference_texts": list(row.get("reference_texts") or []),
                }
            else:
                current["relation_types"] = list(dict.fromkeys(list(current.get("relation_types") or []) + relation_types))
                current["reference_texts"] = list(
                    dict.fromkeys(list(current.get("reference_texts") or []) + list(row.get("reference_texts") or []))
                )
                current["relation_confidence"] = max(
                    float(current.get("relation_confidence") or 0),
                    float(row.get("relation_confidence") or 0),
                )

    return {
        "law_nodes": sorted(law_nodes.values(), key=lambda row: str(row.get("law_uid") or "")),
        "article_nodes": sorted(article_nodes.values(), key=lambda row: str(row.get("article_uid") or "")),
        "has_article_edges": sorted(has_article_edges.values(), key=lambda row: str(row.get("edge_id") or "")),
        "has_child_law_edges": has_child_law_edges,
        "refers_to_law_edges": sorted(refers_to_law_edges.values(), key=lambda row: str(row.get("edge_id") or "")),
        "refers_to_article_edges": sorted(refers_to_article_edges.values(), key=lambda row: str(row.get("edge_id") or "")),
    }


def write_law_graph_export(
    output_dir: str | Path,
    *,
    legal_corpus_path: str | Path = "data/dataset/legal_corpus.jsonl",
    legal_relations_path: str | Path = "data/dataset/legal_relations.jsonl",
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    rows = build_law_graph_export_rows(
        legal_corpus_path=legal_corpus_path,
        legal_relations_path=legal_relations_path,
    )

    write_jsonl(rows["law_nodes"], output_dir / "graph_law_nodes.jsonl")
    write_jsonl(rows["article_nodes"], output_dir / "graph_article_nodes.jsonl")
    write_jsonl(rows["has_article_edges"], output_dir / "graph_edges_has_article.jsonl")
    write_jsonl(rows["has_child_law_edges"], output_dir / "graph_edges_has_child_law.jsonl")
    write_jsonl(rows["refers_to_law_edges"], output_dir / "graph_edges_refers_to_law.jsonl")
    write_jsonl(rows["refers_to_article_edges"], output_dir / "graph_edges_refers_to_article.jsonl")

    manifest = {
        "law_node_count": len(rows["law_nodes"]),
        "article_node_count": len(rows["article_nodes"]),
        "has_article_edge_count": len(rows["has_article_edges"]),
        "has_child_law_edge_count": len(rows["has_child_law_edges"]),
        "refers_to_law_edge_count": len(rows["refers_to_law_edges"]),
        "refers_to_article_edge_count": len(rows["refers_to_article_edges"]),
        "source_legal_corpus_path": str(legal_corpus_path),
        "source_legal_relations_path": str(legal_relations_path),
    }
    _write_json(output_dir / "graph_manifest.json", manifest)
    return manifest
