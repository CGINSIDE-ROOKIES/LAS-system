from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from src.common.io_utils import _iter_jsonl, _write_json, write_jsonl
from src.common.law_meta import normalize_classified_level
from src.parser.law_reference_parser import parse_law_article_references


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


def _merge_string_list(existing: list[str] | None, new_values: list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for value in list(existing or []) + list(new_values or []):
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)

    return merged


def _normalized_law_level(row: dict[str, Any]) -> str:
    return normalize_classified_level(row.get("kind_name"), row.get("classified_level"))


def _law_level_rank(classified_level: Any, kind_name: Any = None) -> int:
    level = normalize_classified_level(kind_name, classified_level)
    if level == "법":
        return 0
    if level == "시행령":
        return 1
    if level == "시행규칙":
        return 2
    return 3


def _law_branch_key(node: dict[str, Any], *, root_law_name: str | None) -> str | None:
    law_name = _clean_str(node.get("law_name"))
    if not law_name:
        return None

    root_name = _clean_str(root_law_name)
    level = _normalized_law_level(node)
    if root_name and level in {"시행령", "시행규칙"} and law_name.startswith(root_name):
        return _family_key(root_name)

    stem = law_name
    for suffix in ("시행규칙", "시행령", "대통령령", "부령", "규칙", "조례", "규정", "훈령", "예규", "고시"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)].strip()
            break

    return _family_key(stem) or _family_key(law_name)


def _build_family_index(law_nodes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for node in law_nodes.values():
        family_id = (
            str(node.get("root_law_uid") or "").strip()
            or _family_key(node.get("root_law_name"))
            or _family_key(node.get("law_name"))
            or str(node.get("law_uid") or "").strip()
        )
        if not family_id:
            continue
        grouped.setdefault(family_id, []).append(node)

    families: dict[str, dict[str, Any]] = {}
    for nodes in grouped.values():
        ordered = sorted(
            nodes,
            key=lambda row: (
                _law_level_rank(row.get("classified_level"), row.get("kind_name")),
                str(row.get("law_name") or ""),
                str(row.get("law_uid") or ""),
            ),
        )
        if not ordered:
            continue

        root = next((row for row in ordered if _normalized_law_level(row) == "법"), ordered[0])
        root_uid = str(root.get("law_uid") or "").strip()
        root_name = _clean_str(root.get("law_name"))
        if not root_uid or not root_name:
            continue

        decrees_by_branch: dict[str, list[dict[str, Any]]] = {}
        rules_by_branch: dict[str, list[dict[str, Any]]] = {}
        branch_by_uid: dict[str, str] = {}
        level_by_uid: dict[str, str] = {}

        for node in ordered:
            law_uid = str(node.get("law_uid") or "").strip()
            if not law_uid:
                continue
            level = _normalized_law_level(node)
            branch_key = _law_branch_key(node, root_law_name=root_name) or root_uid
            branch_by_uid[law_uid] = branch_key
            level_by_uid[law_uid] = level
            if level == "시행령":
                decrees_by_branch.setdefault(branch_key, []).append(node)
            elif level == "시행규칙":
                rules_by_branch.setdefault(branch_key, []).append(node)

        families[root_uid] = {
            "root": root,
            "root_law_uid": root_uid,
            "root_law_name": root_name,
            "root_branch_key": _law_branch_key(root, root_law_name=root_name) or root_uid,
            "nodes": ordered,
            "branch_by_uid": branch_by_uid,
            "level_by_uid": level_by_uid,
            "decrees_by_branch": decrees_by_branch,
            "rules_by_branch": rules_by_branch,
        }

    return families


def _unique_family_member(family: dict[str, Any], *, level: str, branch_key: str | None) -> dict[str, Any] | None:
    if not branch_key:
        return None

    if level == "시행령":
        candidates = list(family.get("decrees_by_branch", {}).get(branch_key, []))
    elif level == "시행규칙":
        candidates = list(family.get("rules_by_branch", {}).get(branch_key, []))
    else:
        return None

    return candidates[0] if len(candidates) == 1 else None


def _build_has_child_law_edges(family_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    has_child_law_edges: dict[str, dict[str, Any]] = {}

    for family in family_index.values():
        root_law_uid = str(family.get("root_law_uid") or "").strip()
        root_law_name = _clean_str(family.get("root_law_name"))
        if not root_law_uid or not root_law_name:
            continue

        for node in family.get("nodes", []):
            law_uid = str(node.get("law_uid") or "").strip()
            if not law_uid or law_uid == root_law_uid:
                continue

            level = str(family.get("level_by_uid", {}).get(law_uid) or "").strip()
            parent_law_uid = root_law_uid

            if level == "시행규칙":
                branch_key = family.get("branch_by_uid", {}).get(law_uid)
                decree_node = _unique_family_member(family, level="시행령", branch_key=branch_key)
                decree_uid = str(decree_node.get("law_uid") or "").strip() if decree_node else None
                if decree_uid and decree_uid != law_uid:
                    parent_law_uid = decree_uid

            edge_key = _edge_id("HAS_CHILD_LAW", parent_law_uid, law_uid)
            has_child_law_edges.setdefault(
                edge_key,
                {
                    "edge_id": edge_key,
                    "edge_type": "HAS_CHILD_LAW",
                    "source_law_uid": parent_law_uid,
                    "target_law_uid": law_uid,
                    "root_law_uid": root_law_uid,
                    "root_law_name": root_law_name,
                },
            )

    return sorted(has_child_law_edges.values(), key=lambda row: str(row.get("edge_id") or ""))


_PRESIDENTIAL_DELEGATION_PATTERN = re.compile(r"대통령령")
_MINISTERIAL_DELEGATION_PATTERN = re.compile(r"(?:[가-힣]+부령|부령|규칙)")


def _build_delegates_to_law_edges(
    *,
    law_nodes: dict[str, dict[str, Any]],
    article_nodes: dict[str, dict[str, Any]],
    family_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for article in article_nodes.values():
        source_law_uid = str(article.get("law_uid") or "").strip()
        source_article_key = str(article.get("article_key") or "").strip()
        root_law_uid = str(article.get("root_law_uid") or "").strip()
        text = str(article.get("text") or "")
        source_law = law_nodes.get(source_law_uid, {})
        family = family_index.get(root_law_uid, {})
        source_level = _normalized_law_level(source_law) if source_law else None
        branch_key = family.get("branch_by_uid", {}).get(source_law_uid)
        if not source_law_uid or not source_article_key or not root_law_uid or not text or not branch_key:
            continue

        target_node: dict[str, Any] | None = None
        relation_type: str | None = None

        if source_level == "법" and _PRESIDENTIAL_DELEGATION_PATTERN.search(text):
            target_node = _unique_family_member(family, level="시행령", branch_key=branch_key)
            relation_type = "presidential_decree"
        elif source_level == "시행령" and _MINISTERIAL_DELEGATION_PATTERN.search(text):
            target_node = _unique_family_member(family, level="시행규칙", branch_key=branch_key)
            relation_type = "ministerial_rule"
        elif source_level == "법" and _MINISTERIAL_DELEGATION_PATTERN.search(text):
            decree_node = _unique_family_member(family, level="시행령", branch_key=branch_key)
            if decree_node is None:
                target_node = _unique_family_member(family, level="시행규칙", branch_key=branch_key)
                relation_type = "ministerial_rule"

        target_law_uid = str(target_node.get("law_uid") or "").strip() if target_node else None
        if not target_law_uid or not relation_type or target_law_uid == source_law_uid:
            continue

        edge_key = _edge_id("DELEGATES_TO_LAW", source_law_uid, target_law_uid)
        current = merged.get(edge_key)
        reference_text = _clean_str(article.get("article_no_display")) or source_article_key
        if current is None:
            merged[edge_key] = {
                "edge_id": edge_key,
                "edge_type": "DELEGATES_TO_LAW",
                "source_law_uid": source_law_uid,
                "target_law_uid": target_law_uid,
                "root_law_uid": root_law_uid,
                "root_law_name": article.get("root_law_name"),
                "relation_type": relation_type,
                "relation_types": [relation_type, "delegation"],
                "relation_confidence": 0.9,
                "source_article_keys": [source_article_key],
                "source_article_no_displays": [_clean_str(article.get("article_no_display"))] if _clean_str(article.get("article_no_display")) else [],
                "reference_texts": [reference_text],
            }
            continue

        current["source_article_keys"] = _merge_string_list(current.get("source_article_keys"), [source_article_key])
        article_no_display = _clean_str(article.get("article_no_display"))
        if article_no_display:
            current["source_article_no_displays"] = _merge_string_list(
                current.get("source_article_no_displays"),
                [article_no_display],
            )
        current["reference_texts"] = _merge_string_list(current.get("reference_texts"), [reference_text])

    return sorted(merged.values(), key=lambda row: str(row.get("edge_id") or ""))


def _build_law_name_index(law_nodes: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for node in law_nodes.values():
        key = _family_key(node.get("law_name"))
        if not key:
            continue
        index.setdefault(key, []).append(node)
    return index


def _resolve_target_law_node(
    reference: dict[str, Any],
    *,
    law_name_index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    target_law_name = _clean_str(reference.get("target_law_name"))
    if target_law_name:
        direct_matches = list(law_name_index.get(_family_key(target_law_name) or "", []))
        if len(direct_matches) == 1:
            return direct_matches[0]

    candidate_nodes: dict[str, dict[str, Any]] = {}
    for candidate_name in [target_law_name] + list(reference.get("related_law_names") or []):
        key = _family_key(candidate_name)
        if not key:
            continue
        for node in law_name_index.get(key, []):
            law_uid = str(node.get("law_uid") or "").strip()
            if law_uid:
                candidate_nodes[law_uid] = node

    return next(iter(candidate_nodes.values())) if len(candidate_nodes) == 1 else None


def _reference_article_details(reference: dict[str, Any]) -> list[dict[str, str | None]]:
    details: list[dict[str, str | None]] = []
    for detail in list(reference.get("target_article_ref_details") or []):
        article_key = str(detail.get("article_key") or "").strip()
        if not article_key:
            continue
        details.append(
            {
                "article_key": article_key,
                "article_no_display": _clean_str(detail.get("article_no_display")) or article_key,
                "paragraph_no": _clean_str(detail.get("paragraph_no")),
                "item_no": _clean_str(detail.get("item_no")),
                "subitem_no": _clean_str(detail.get("subitem_no")),
            }
        )

    if details:
        return details

    article_keys = [str(item).strip() for item in list(reference.get("target_article_keys") or []) if str(item).strip()]
    article_no_displays = [str(item).strip() for item in list(reference.get("target_article_no_displays") or []) if str(item).strip()]
    display_by_key = dict(zip(article_keys, article_no_displays))
    return [
        {
            "article_key": article_key,
            "article_no_display": display_by_key.get(article_key) or article_key,
            "paragraph_no": None,
            "item_no": None,
            "subitem_no": None,
        }
        for article_key in article_keys
    ]


def _build_relation_types(
    *,
    base_relation_type: str,
    reference_type: str,
    source_law_uid: str,
    target_law_uid: str,
) -> list[str]:
    relation_types = [base_relation_type, reference_type]
    if source_law_uid == target_law_uid:
        relation_types.append("same_law_reference")
    if reference_type in {"previous_article", "next_article", "current_article", "relative_scope"}:
        relation_types.append("relative_reference")
    if reference_type == "bare_law_name":
        relation_types.append("explicit_law_name")
    return _merge_string_list([], relation_types)


def _compile_flexible_space_pattern(text: str, *, with_boundaries: bool) -> re.Pattern[str] | None:
    normalized = str(text or "").strip()
    if not normalized:
        return None
    tokens = [re.escape(token) for token in re.split(r"\s+", normalized) if token]
    if not tokens:
        return None
    joined = r"\s*".join(tokens)
    if with_boundaries:
        joined = rf"(?<![가-힣0-9]){joined}"
    return re.compile(joined)


def _mask_first(text: str, fragment: str) -> str:
    pattern = _compile_flexible_space_pattern(fragment, with_boundaries=False)
    if pattern is None:
        return text
    match = pattern.search(text)
    if match is None:
        return text
    return text[: match.start()] + (" " * (match.end() - match.start())) + text[match.end() :]


def _extract_bare_law_mentions(
    text: str,
    *,
    law_nodes: dict[str, dict[str, Any]],
    parsed_references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    masked_text = str(text or "")
    for fragment in sorted(
        {
            str(reference.get("reference_text") or "").strip()
            for reference in parsed_references
            if str(reference.get("reference_text") or "").strip()
        },
        key=len,
        reverse=True,
    ):
        masked_text = _mask_first(masked_text, fragment)

    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = sorted(
        (
            _clean_str(node.get("law_name"))
            for node in law_nodes.values()
            if _clean_str(node.get("law_name"))
        ),
        key=lambda value: (-len(str(value or "")), str(value or "")),
    )

    for law_name in candidates:
        if not law_name:
            continue
        pattern = _compile_flexible_space_pattern(law_name, with_boundaries=True)
        if pattern is None:
            continue

        while True:
            match = pattern.search(masked_text)
            if match is None:
                break

            if law_name not in seen:
                seen.add(law_name)
                mentions.append(
                    {
                        "law_name": law_name,
                        "reference_text": _clean_str(match.group(0)) or law_name,
                        "resolution_confidence": 0.8,
                    }
                )

            masked_text = masked_text[: match.start()] + (" " * (match.end() - match.start())) + masked_text[match.end() :]

    return mentions


def _upsert_refers_to_law_edge(
    merged: dict[str, dict[str, Any]],
    *,
    source_law_uid: str,
    target_law_uid: str,
    root_law_uid: str,
    root_law_name: str | None,
    source_article_key: str,
    source_article_no_display: str | None,
    relation_types: list[str],
    relation_confidence: float,
    reference_text: str,
    target_article_details: list[dict[str, str | None]] | None = None,
) -> None:
    if not source_law_uid or not target_law_uid or source_law_uid == target_law_uid:
        return

    target_article_details = list(target_article_details or [])
    edge_key = _edge_id("REFERS_TO_LAW", source_law_uid, target_law_uid)
    target_article_keys = [str(item.get("article_key") or "").strip() for item in target_article_details if str(item.get("article_key") or "").strip()]
    target_article_no_displays = [str(item.get("article_no_display") or "").strip() for item in target_article_details if str(item.get("article_no_display") or "").strip()]
    target_paragraph_nos = [str(item.get("paragraph_no") or "").strip() for item in target_article_details if str(item.get("paragraph_no") or "").strip()]
    target_item_nos = [str(item.get("item_no") or "").strip() for item in target_article_details if str(item.get("item_no") or "").strip()]
    target_subitem_nos = [str(item.get("subitem_no") or "").strip() for item in target_article_details if str(item.get("subitem_no") or "").strip()]

    current = merged.get(edge_key)
    if current is None:
        merged[edge_key] = {
            "edge_id": edge_key,
            "edge_type": "REFERS_TO_LAW",
            "source_law_uid": source_law_uid,
            "target_law_uid": target_law_uid,
            "root_law_uid": root_law_uid,
            "root_law_name": root_law_name,
            "relation_type": "cited_law",
            "relation_types": _merge_string_list([], relation_types),
            "resolution_status": "resolved",
            "relation_confidence": relation_confidence,
            "source_article_keys": [source_article_key],
            "source_article_no_displays": [source_article_no_display] if source_article_no_display else [],
            "target_article_keys": target_article_keys,
            "target_article_no_displays": target_article_no_displays,
            "target_paragraph_nos": target_paragraph_nos,
            "target_item_nos": target_item_nos,
            "target_subitem_nos": target_subitem_nos,
            "reference_texts": [reference_text],
        }
        return

    current["relation_types"] = _merge_string_list(current.get("relation_types"), relation_types)
    current["relation_confidence"] = max(float(current.get("relation_confidence") or 0), relation_confidence)
    current["source_article_keys"] = _merge_string_list(current.get("source_article_keys"), [source_article_key])
    current["source_article_no_displays"] = _merge_string_list(
        current.get("source_article_no_displays"),
        [source_article_no_display] if source_article_no_display else [],
    )
    current["target_article_keys"] = _merge_string_list(current.get("target_article_keys"), target_article_keys)
    current["target_article_no_displays"] = _merge_string_list(
        current.get("target_article_no_displays"),
        target_article_no_displays,
    )
    current["target_paragraph_nos"] = _merge_string_list(current.get("target_paragraph_nos"), target_paragraph_nos)
    current["target_item_nos"] = _merge_string_list(current.get("target_item_nos"), target_item_nos)
    current["target_subitem_nos"] = _merge_string_list(current.get("target_subitem_nos"), target_subitem_nos)
    current["reference_texts"] = _merge_string_list(current.get("reference_texts"), [reference_text])


def _upsert_refers_to_article_edge(
    merged: dict[str, dict[str, Any]],
    *,
    source_article_uid: str,
    target_article_uid: str,
    source_law_uid: str,
    target_law_uid: str,
    source_article_key: str,
    source_article_no_display: str | None,
    target_detail: dict[str, str | None],
    relation_types: list[str],
    relation_confidence: float,
    reference_text: str,
) -> None:
    if not source_article_uid or not target_article_uid or source_article_uid == target_article_uid:
        return

    edge_key = _edge_id("REFERS_TO_ARTICLE", source_article_uid, target_article_uid)
    target_article_key = str(target_detail.get("article_key") or "").strip()
    target_article_no_display = _clean_str(target_detail.get("article_no_display")) or target_article_key
    target_paragraph_no = _clean_str(target_detail.get("paragraph_no"))
    target_item_no = _clean_str(target_detail.get("item_no"))
    target_subitem_no = _clean_str(target_detail.get("subitem_no"))

    current = merged.get(edge_key)
    if current is None:
        merged[edge_key] = {
            "edge_id": edge_key,
            "edge_type": "REFERS_TO_ARTICLE",
            "source_article_uid": source_article_uid,
            "target_article_uid": target_article_uid,
            "source_law_uid": source_law_uid,
            "target_law_uid": target_law_uid,
            "source_article_key": source_article_key,
            "source_article_no_display": source_article_no_display,
            "target_article_key": target_article_key,
            "target_article_no_display": target_article_no_display,
            "relation_type": "related_law",
            "relation_types": _merge_string_list([], relation_types),
            "resolution_status": "resolved",
            "relation_confidence": relation_confidence,
            "target_paragraph_nos": [target_paragraph_no] if target_paragraph_no else [],
            "target_item_nos": [target_item_no] if target_item_no else [],
            "target_subitem_nos": [target_subitem_no] if target_subitem_no else [],
            "reference_texts": [reference_text],
        }
        return

    current["relation_types"] = _merge_string_list(current.get("relation_types"), relation_types)
    current["relation_confidence"] = max(float(current.get("relation_confidence") or 0), relation_confidence)
    current["target_paragraph_nos"] = _merge_string_list(
        current.get("target_paragraph_nos"),
        [target_paragraph_no] if target_paragraph_no else [],
    )
    current["target_item_nos"] = _merge_string_list(
        current.get("target_item_nos"),
        [target_item_no] if target_item_no else [],
    )
    current["target_subitem_nos"] = _merge_string_list(
        current.get("target_subitem_nos"),
        [target_subitem_no] if target_subitem_no else [],
    )
    current["reference_texts"] = _merge_string_list(current.get("reference_texts"), [reference_text])


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
    delegates_to_law_edges: list[dict[str, Any]] = []
    refers_to_law_edges: dict[str, dict[str, Any]] = {}
    refers_to_article_edges: dict[str, dict[str, Any]] = {}
    article_orders_by_law: dict[str, list[dict[str, str]]] = {}
    seen_article_keys_by_law: dict[str, set[str]] = {}

    for row in _iter_jsonl(legal_corpus_path):
        if str(row.get("doc_type") or "").strip() != "law":
            continue
        if str(row.get("section_type") or "").strip() != "article":
            continue

        law_uid = str(row.get("law_uid") or "").strip()
        law_name = _clean_str(row.get("law_name"))
        article_key = str(row.get("article_key") or "").strip()
        article_uid = _article_uid(law_uid, article_key)
        normalized_level = normalize_classified_level(row.get("kind_name"), row.get("classified_level"))
        if not law_uid or not law_name or not article_uid:
            continue

        if law_uid not in law_nodes:
            law_nodes[law_uid] = {
                "node_type": "Law",
                "law_uid": law_uid,
                "law_name": law_name,
                "root_law_uid": row.get("root_law_uid"),
                "root_law_name": row.get("root_law_name"),
                "classified_level": normalized_level,
                "kind_name": row.get("kind_name"),
                "ef_yd": row.get("ef_yd"),
                "law_id": row.get("law_id"),
                "mst": row.get("mst"),
            }

        seen_article_keys_by_law.setdefault(law_uid, set())
        if article_key and article_key not in seen_article_keys_by_law[law_uid]:
            article_orders_by_law.setdefault(law_uid, []).append(
                {
                    "article_key": article_key,
                    "article_no_display": str(row.get("article_no_display") or article_key).strip(),
                }
            )
            seen_article_keys_by_law[law_uid].add(article_key)

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
                "classified_level": normalized_level,
                "kind_name": row.get("kind_name"),
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
            _law_level_rank(row.get("classified_level"), row.get("kind_name")),
            str(row.get("law_name") or ""),
        ),
    ):
        family_key = _family_key(node.get("root_law_name")) or _family_key(node.get("law_name"))
        if not family_key:
            continue
        current = family_roots.get(family_key)
        if current is None or _law_level_rank(node.get("classified_level"), node.get("kind_name")) < _law_level_rank(
            current.get("classified_level"),
            current.get("kind_name"),
        ):
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

    family_index = _build_family_index(law_nodes)
    family_laws_by_root_uid = {
        root_uid: [
            {
                "law_name": node.get("law_name"),
                "classified_level": node.get("classified_level"),
                "kind_name": node.get("kind_name"),
            }
            for node in family.get("nodes", [])
        ]
        for root_uid, family in family_index.items()
    }
    law_name_index = _build_law_name_index(law_nodes)

    has_child_law_edges = _build_has_child_law_edges(family_index)
    delegates_to_law_edges = _build_delegates_to_law_edges(
        law_nodes=law_nodes,
        article_nodes=article_nodes,
        family_index=family_index,
    )

    for article in article_nodes.values():
        source_law_uid = str(article.get("law_uid") or "").strip()
        source_article_uid = str(article.get("article_uid") or "").strip()
        source_article_key = str(article.get("article_key") or "").strip()
        root_law_uid = str(article.get("root_law_uid") or "").strip()
        source_law_name = _clean_str(article.get("law_name"))
        source_article_no_display = _clean_str(article.get("article_no_display"))
        text = str(article.get("text") or "")
        if not source_law_uid or not source_article_uid or not source_article_key or not root_law_uid or not source_law_name or not text:
            continue

        parsed_references = parse_law_article_references(
            text,
            source_law_name=source_law_name,
            source_law_level=article.get("classified_level"),
            source_article_key=source_article_key,
            article_order=article_orders_by_law.get(source_law_uid, []),
            root_law_name=_clean_str(article.get("root_law_name")) or source_law_name,
            family_laws=family_laws_by_root_uid.get(root_law_uid, []),
        )

        for reference in parsed_references:
            target_node = _resolve_target_law_node(reference, law_name_index=law_name_index)
            if target_node is None:
                continue

            target_law_uid = str(target_node.get("law_uid") or "").strip()
            if not target_law_uid:
                continue

            relation_confidence = float(reference.get("resolution_confidence") or 0.9)
            reference_text = _clean_str(reference.get("reference_text")) or source_article_no_display or source_article_key
            reference_type = str(reference.get("reference_type") or "").strip() or "article_reference"
            detail_list = _reference_article_details(reference)
            relation_types = _build_relation_types(
                base_relation_type="related_law",
                reference_type=reference_type,
                source_law_uid=source_law_uid,
                target_law_uid=target_law_uid,
            )

            created_article_edge = False
            for detail in detail_list:
                target_article_uid = _article_uid(target_law_uid, detail.get("article_key"))
                if not target_article_uid or target_article_uid not in article_nodes or target_article_uid == source_article_uid:
                    continue
                _upsert_refers_to_article_edge(
                    refers_to_article_edges,
                    source_article_uid=source_article_uid,
                    target_article_uid=target_article_uid,
                    source_law_uid=source_law_uid,
                    target_law_uid=target_law_uid,
                    source_article_key=source_article_key,
                    source_article_no_display=source_article_no_display,
                    target_detail=detail,
                    relation_types=relation_types,
                    relation_confidence=relation_confidence,
                    reference_text=reference_text,
                )
                created_article_edge = True

            if (not detail_list or not created_article_edge) and source_law_uid != target_law_uid:
                _upsert_refers_to_law_edge(
                    refers_to_law_edges,
                    source_law_uid=source_law_uid,
                    target_law_uid=target_law_uid,
                    root_law_uid=root_law_uid,
                    root_law_name=_clean_str(article.get("root_law_name")) or source_law_name,
                    source_article_key=source_article_key,
                    source_article_no_display=source_article_no_display,
                    relation_types=_build_relation_types(
                        base_relation_type="cited_law",
                        reference_type=reference_type,
                        source_law_uid=source_law_uid,
                        target_law_uid=target_law_uid,
                    ),
                    relation_confidence=relation_confidence,
                    reference_text=reference_text,
                    target_article_details=detail_list,
                )

        for mention in _extract_bare_law_mentions(text, law_nodes=law_nodes, parsed_references=parsed_references):
            target_nodes = list(law_name_index.get(_family_key(mention.get("law_name")) or "", []))
            if len(target_nodes) != 1:
                continue
            target_law_uid = str(target_nodes[0].get("law_uid") or "").strip()
            if not target_law_uid or target_law_uid == source_law_uid:
                continue

            _upsert_refers_to_law_edge(
                refers_to_law_edges,
                source_law_uid=source_law_uid,
                target_law_uid=target_law_uid,
                root_law_uid=root_law_uid,
                root_law_name=_clean_str(article.get("root_law_name")) or source_law_name,
                source_article_key=source_article_key,
                source_article_no_display=source_article_no_display,
                relation_types=_build_relation_types(
                    base_relation_type="cited_law",
                    reference_type="bare_law_name",
                    source_law_uid=source_law_uid,
                    target_law_uid=target_law_uid,
                ),
                relation_confidence=float(mention.get("resolution_confidence") or 0.8),
                reference_text=_clean_str(mention.get("reference_text")) or str(mention.get("law_name") or "").strip(),
                target_article_details=[],
            )

    return {
        "law_nodes": sorted(law_nodes.values(), key=lambda row: str(row.get("law_uid") or "")),
        "article_nodes": sorted(article_nodes.values(), key=lambda row: str(row.get("article_uid") or "")),
        "has_article_edges": sorted(has_article_edges.values(), key=lambda row: str(row.get("edge_id") or "")),
        "has_child_law_edges": has_child_law_edges,
        "delegates_to_law_edges": delegates_to_law_edges,
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
    write_jsonl(rows["delegates_to_law_edges"], output_dir / "graph_edges_delegates_to_law.jsonl")
    write_jsonl(rows["refers_to_law_edges"], output_dir / "graph_edges_refers_to_law.jsonl")
    write_jsonl(rows["refers_to_article_edges"], output_dir / "graph_edges_refers_to_article.jsonl")

    manifest = {
        "law_node_count": len(rows["law_nodes"]),
        "article_node_count": len(rows["article_nodes"]),
        "has_article_edge_count": len(rows["has_article_edges"]),
        "has_child_law_edge_count": len(rows["has_child_law_edges"]),
        "delegates_to_law_edge_count": len(rows["delegates_to_law_edges"]),
        "refers_to_law_edge_count": len(rows["refers_to_law_edges"]),
        "refers_to_article_edge_count": len(rows["refers_to_article_edges"]),
        "source_legal_corpus_path": str(legal_corpus_path),
        "source_legal_relations_path": str(legal_relations_path),
    }
    _write_json(output_dir / "graph_manifest.json", manifest)
    return manifest
