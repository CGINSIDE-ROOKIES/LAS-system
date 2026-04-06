"""Build `law_to_law` rows from normalized law articles.

Observed relation examples from the current dataset:
- `cited_law`: `건설산업기본법 시행령` -> `건설산업기본법`
- `same_law_reference`: `파견근로자 보호 등에 관한 법률 제21조의2` -> same law
- `relative_reference`: `같은 법 제9조`, `동조`
- `external_reference`: currently includes noisy cases like `국토교통부장관(법 제91조`
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from src.common.io_utils import _read_json
from src.common.law_meta import build_law_uid, build_strict_law_uid
from src.parser.legal_case_parser import (
    extract_explicit_article_refs,
    find_related_law_names,
)
from src.parser.law_reference_parser import parse_law_article_references


def _normalize_space(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _truncate_text(text: str, limit: int = 320) -> str:
    normalized = _normalize_space(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _iter_law_payloads(normalized_base_dir: Path):
    for path in sorted(normalized_base_dir.rglob("*__parsed_law.json")):
        payload = _read_json(path)
        root_law_name = path.parent.name.replace("_", " ").strip() or str(payload.get("law_name") or "").strip()
        yield path, root_law_name, payload


def _article_text(article: dict[str, Any]) -> str:
    parts = [
        str(article.get("article_no_display") or article.get("article_no") or "").strip(),
        str(article.get("article_title_raw") or article.get("article_title") or "").strip(),
        str(article.get("article_text_raw") or article.get("article_text") or "").strip(),
    ]
    return "\n".join(part for part in parts if part).strip()


def _article_reference_text(article: dict[str, Any]) -> str:
    parts: list[str] = []

    article_text = str(article.get("article_text_raw") or article.get("article_text") or "").strip()
    if article_text:
        parts.append(article_text)

    for paragraph in article.get("paragraphs", []) if isinstance(article.get("paragraphs"), list) else []:
        if not isinstance(paragraph, dict):
            continue
        paragraph_text = str(paragraph.get("paragraph_text_raw") or paragraph.get("paragraph_text") or "").strip()
        if paragraph_text:
            parts.append(paragraph_text)
        for item in paragraph.get("items", []) if isinstance(paragraph.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            item_text = str(item.get("item_text_raw") or item.get("item_text") or "").strip()
            if item_text:
                parts.append(item_text)
            for subitem in item.get("subitems", []) if isinstance(item.get("subitems"), list) else []:
                if not isinstance(subitem, dict):
                    continue
                subitem_text = str(subitem.get("subitem_text_raw") or subitem.get("subitem_text") or "").strip()
                if subitem_text:
                    parts.append(subitem_text)

    return "\n".join(part for part in parts if part).strip()


def _relation_text(row: dict[str, Any]) -> str:
    lines = [
        f"관계 모델: {row.get('relation_model') or ''}",
        f"출발 법령: {row.get('source_law_name') or ''}",
        f"출발 조문: {row.get('source_article_no_display') or row.get('article_no_display') or ''}",
        f"대상 법령: {row.get('law_name') or ''}",
        f"관계 유형: {row.get('relation_type') or ''}",
        f"해석 상태: {row.get('resolution_status') or ''}",
    ]
    article_displays = row.get("article_no_displays") or []
    if article_displays:
        lines.append(f"관련 조문: {', '.join(article_displays)}")
    reference_texts = row.get("reference_texts") or []
    if reference_texts:
        lines.append(f"참조 표현: {', '.join(reference_texts)}")
    preview = str(row.get("display_text") or "").strip()
    if preview:
        lines.append("근거 일부:")
        lines.append(preview)
    return "\n".join(line for line in lines if line).strip()


def _family_laws_by_alias(root_law_name: str, laws: list[dict[str, Any]]) -> dict[str, list[str]]:
    alias_map: dict[str, list[str]] = {}

    def add(alias: str, law_name: str) -> None:
        key = "".join(str(alias or "").split())
        value = str(law_name or "").strip()
        if not key or not value:
            return
        alias_map.setdefault(key, [])
        if value not in alias_map[key]:
            alias_map[key].append(value)

    for law in laws:
        law_name = str(law.get("law_name") or "").strip()
        if not law_name:
            continue
        add(law_name, law_name)
        suffix = law_name
        if root_law_name and law_name.startswith(root_law_name):
            suffix = law_name[len(root_law_name):].strip()
        if suffix and suffix != law_name:
            add(suffix, law_name)
    return alias_map


def _relation_resolution_status(values: list[str]) -> str:
    priority = ["resolved", "ambiguous", "unresolved_external", "unresolved"]
    normalized = {str(value or "").strip() for value in values if str(value or "").strip()}
    for candidate in priority:
        if candidate in normalized:
            return candidate
    return "unresolved"


def build_law_to_law_relation_records(
    normalized_base_dir: str | Path = "data/normalized/01_current_law",
) -> list[dict[str, Any]]:
    normalized_base_dir = Path(normalized_base_dir)
    laws_by_root: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for path, root_law_name, payload in _iter_law_payloads(normalized_base_dir):
        law_name = str(payload.get("law_name") or "").strip()
        if not law_name:
            continue
        laws_by_root[root_law_name].append(
            {
                "path": path,
                "root_law_name": root_law_name,
                "root_law_uid": build_strict_law_uid(payload.get("law_id"), payload.get("mst")),
                "law_name": law_name,
                "law_id": payload.get("law_id"),
                "mst": payload.get("mst"),
                "law_uid": build_law_uid(payload.get("law_id"), payload.get("mst"), law_name),
                "payload": payload,
            }
        )

    merged: dict[str, dict[str, Any]] = {}

    for root_law_name, laws in sorted(laws_by_root.items()):
        family_law_names = [row["law_name"] for row in laws]
        uid_by_name = {row["law_name"]: row["law_uid"] for row in laws}
        law_meta_by_name = {row["law_name"]: row for row in laws}
        root_law_uid = uid_by_name.get(root_law_name) or build_strict_law_uid(
            law_meta_by_name.get(root_law_name, {}).get("law_id"),
            law_meta_by_name.get(root_law_name, {}).get("mst"),
        )
        family_alias_map = _family_laws_by_alias(root_law_name, laws)

        for source in laws:
            payload = source["payload"]
            articles = payload.get("articles", [])
            article_order = [
                {
                    "article_key": str(
                        article.get("article_key")
                        or article.get("article_no_display")
                        or article.get("article_no")
                        or ""
                    ).strip(),
                    "article_no_display": str(article.get("article_no_display") or article.get("article_no") or "").strip(),
                }
                for article in articles
                if isinstance(article, dict)
            ]
            for article in articles if isinstance(articles, list) else []:
                if not isinstance(article, dict):
                    continue

                article_key = str(
                    article.get("article_key")
                    or article.get("article_no_display")
                    or article.get("article_no")
                    or ""
                ).strip()
                body_text = _article_text(article)
                reference_text = _article_reference_text(article)
                if not reference_text:
                    continue

                parsed_refs = parse_law_article_references(
                    reference_text,
                    source_law_name=source["law_name"],
                    source_law_level=payload.get("classified_level") or payload.get("kind_name"),
                    source_article_key=article_key or None,
                    article_order=article_order,
                    root_law_name=root_law_name,
                    family_laws=[
                        {
                            "law_name": row["law_name"],
                            "classified_level": row["payload"].get("classified_level"),
                            "kind_name": row["payload"].get("kind_name"),
                        }
                        for row in laws
                    ],
                )
                matched_law_names = [
                    law_name
                    for law_name in find_related_law_names(reference_text, family_law_names)
                    if law_name and law_name != source["law_name"]
                ]
                article_refs_map = extract_explicit_article_refs(reference_text, family_law_names)

                refs_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
                for reference in parsed_refs:
                    target_law_name = str(reference.get("target_law_name") or "").strip()
                    if not target_law_name:
                        continue
                    refs_by_target[target_law_name].append(reference)

                for target_law_name in matched_law_names:
                    if target_law_name not in refs_by_target:
                        refs_by_target[target_law_name].append(
                            {
                                "reference_type": "cited_law_name",
                                "reference_text": target_law_name,
                                "target_law_name": target_law_name,
                                "related_law_names": family_alias_map.get("".join(target_law_name.split()), [target_law_name]),
                                "target_article_keys": [],
                                "target_article_no_displays": [],
                                "resolution_status": "resolved",
                                "resolution_confidence": 0.8,
                            }
                        )

                for target_law_name, target_refs in sorted(refs_by_target.items()):
                    target_meta = law_meta_by_name.get(target_law_name)
                    target_law_uid = uid_by_name.get(target_law_name) if target_meta else None
                    target_article_refs = article_refs_map.get(target_law_name, [])
                    parsed_article_keys = [
                        article_key
                        for reference in target_refs
                        for article_key in list(reference.get("target_article_keys") or [])
                    ]
                    parsed_article_no_displays = [
                        article_no
                        for reference in target_refs
                        for article_no in list(reference.get("target_article_no_displays") or [])
                    ]
                    article_keys = list(dict.fromkeys(parsed_article_keys or [item["article_key"] for item in target_article_refs]))
                    article_no_displays = list(
                        dict.fromkeys(parsed_article_no_displays or [item["article_no_display"] for item in target_article_refs])
                    )
                    relation_type = "related_law" if article_keys else "cited_law"
                    relation_status = _relation_resolution_status(
                        [str(reference.get("resolution_status") or "") for reference in target_refs]
                    )
                    target_token = target_law_uid or f"external::{target_law_name.replace(' ', '_')}"
                    relation_id = "::".join(
                        [
                            "relation",
                            "law",
                            source["law_uid"],
                            target_token,
                            article_key or "root",
                        ]
                    )
                    current = merged.get(relation_id)
                    if current is None:
                        relation_types = [relation_type]
                        reference_types = {str(reference.get("reference_type") or "").strip() for reference in target_refs}
                        if target_law_name == source["law_name"]:
                            relation_types.append("same_law_reference")
                        if any(reference_type in {"previous_article", "next_article", "current_article", "relative_scope"} for reference_type in reference_types):
                            relation_types.append("relative_reference")
                        if relation_status == "unresolved_external":
                            relation_types.append("external_reference")
                        current = {
                            "id": relation_id,
                            "canonical_id": relation_id,
                            "doc_type": "relation",
                            "source_group": "01_current_law",
                            "relation_model": "law_to_law",
                            "relation_type": relation_type,
                            "relation_types": list(dict.fromkeys(relation_types)),
                            "law_name": target_law_name,
                            "law_uid": target_law_uid,
                            "source_law_name": source["law_name"],
                            "source_law_uid": source["law_uid"],
                            "root_law_name": root_law_name,
                            "root_law_uid": root_law_uid,
                            "related_law_names": list(
                                dict.fromkeys(
                                    [target_law_name]
                                    + [
                                        candidate
                                        for reference in target_refs
                                        for candidate in list(reference.get("related_law_names") or [])
                                        if str(candidate).strip()
                                    ]
                                )
                            ),
                            "article_keys": article_keys,
                            "article_no_displays": article_no_displays,
                            "relation_confidence": max(
                                float(reference.get("resolution_confidence") or 0)
                                for reference in target_refs
                            ) if target_refs else (0.95 if article_keys else 0.8),
                            "resolution_confidence": max(
                                float(reference.get("resolution_confidence") or 0)
                                for reference in target_refs
                            ) if target_refs else (0.95 if article_keys else 0.8),
                            "resolution_status": relation_status,
                            "title": f"{source['law_name']} -> {target_law_name}",
                            "law_id": target_meta.get("law_id") if target_meta else None,
                            "mst": target_meta.get("mst") if target_meta else None,
                            "ef_yd": target_meta["payload"].get("ef_yd") if target_meta else None,
                            "kind_name": target_meta["payload"].get("kind_name") if target_meta else None,
                            "classified_level": target_meta["payload"].get("classified_level") if target_meta else None,
                            "law_level": target_meta["payload"].get("classified_level") if target_meta else None,
                            "source_hit_count": 1,
                            "section_type": "article",
                            "article_key": article_key or None,
                            "article_no_display": article.get("article_no_display") or article.get("article_no"),
                            "source_article_key": article_key or None,
                            "source_article_no_display": article.get("article_no_display") or article.get("article_no"),
                            "target_article_resolution_count": len(article_keys),
                            "reference_texts": list(
                                dict.fromkeys(
                                    [
                                        str(reference.get("reference_text") or "").strip()
                                        for reference in target_refs
                                        if str(reference.get("reference_text") or "").strip()
                                    ]
                                )
                            ),
                            "source_file_path": str(source["path"]),
                            "display_text": _truncate_text(body_text),
                        }
                        merged[relation_id] = current
                        continue

                    current["source_hit_count"] = int(current.get("source_hit_count") or 0) + 1
                    current["relation_confidence"] = max(float(current.get("relation_confidence") or 0), max(
                        [float(reference.get("resolution_confidence") or 0) for reference in target_refs] or [0.95 if article_keys else 0.8]
                    ))
                    current["resolution_confidence"] = max(
                        float(current.get("resolution_confidence") or 0),
                        max([float(reference.get("resolution_confidence") or 0) for reference in target_refs] or [0.95 if article_keys else 0.8]),
                    )
                    current["article_keys"] = list(dict.fromkeys(list(current.get("article_keys", [])) + article_keys))
                    current["article_no_displays"] = list(
                        dict.fromkeys(list(current.get("article_no_displays", [])) + article_no_displays)
                    )
                    extra_relation_types = [relation_type]
                    if target_law_name == source["law_name"]:
                        extra_relation_types.append("same_law_reference")
                    if any(
                        str(reference.get("reference_type") or "").strip() in {"previous_article", "next_article", "current_article", "relative_scope"}
                        for reference in target_refs
                    ):
                        extra_relation_types.append("relative_reference")
                    if relation_status == "unresolved_external":
                        extra_relation_types.append("external_reference")
                    current["relation_types"] = list(dict.fromkeys(list(current.get("relation_types", [])) + extra_relation_types))
                    current["related_law_names"] = list(
                        dict.fromkeys(
                            list(current.get("related_law_names", []))
                            + [
                                candidate
                                for reference in target_refs
                                for candidate in list(reference.get("related_law_names") or [])
                                if str(candidate).strip()
                            ]
                        )
                    )
                    current["reference_texts"] = list(
                        dict.fromkeys(
                            list(current.get("reference_texts", []))
                            + [
                                str(reference.get("reference_text") or "").strip()
                                for reference in target_refs
                                if str(reference.get("reference_text") or "").strip()
                            ]
                        )
                    )
                    current["target_article_resolution_count"] = len(current.get("article_keys", []))
                    current["resolution_status"] = _relation_resolution_status(
                        [current.get("resolution_status")] + [str(reference.get("resolution_status") or "") for reference in target_refs]
                    )
                    if len(str(current.get("display_text") or "")) < len(_truncate_text(body_text)):
                        current["display_text"] = _truncate_text(body_text)

    rows: list[dict[str, Any]] = []
    for row in merged.values():
        text = _relation_text(row)
        row["text"] = text
        row["search_text"] = text
        row["display_text"] = str(row.get("display_text") or _truncate_text(text))
        rows.append(row)

    rows.sort(key=lambda item: str(item.get("id") or ""))
    return rows
