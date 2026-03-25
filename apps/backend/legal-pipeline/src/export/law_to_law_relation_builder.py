from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from src.common.io_utils import _read_json
from src.common.law_meta import build_law_uid
from src.parser.legal_case_parser import (
    extract_explicit_article_refs,
    find_related_law_names,
)


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


def _relation_text(row: dict[str, Any]) -> str:
    lines = [
        f"관계 모델: {row.get('relation_model') or ''}",
        f"출발 법령: {row.get('source_law_name') or ''}",
        f"대상 법령: {row.get('law_name') or ''}",
        f"관계 유형: {row.get('relation_type') or ''}",
    ]
    article_displays = row.get("article_no_displays") or []
    if article_displays:
        lines.append(f"관련 조문: {', '.join(article_displays)}")
    preview = str(row.get("display_text") or "").strip()
    if preview:
        lines.append("근거 일부:")
        lines.append(preview)
    return "\n".join(line for line in lines if line).strip()


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
                "root_law_uid": build_law_uid(None, None, root_law_name),
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

        for source in laws:
            payload = source["payload"]
            for article in payload.get("articles", []) if isinstance(payload.get("articles"), list) else []:
                if not isinstance(article, dict):
                    continue

                article_key = str(
                    article.get("article_key")
                    or article.get("article_no_display")
                    or article.get("article_no")
                    or ""
                ).strip()
                body_text = _article_text(article)
                if not body_text:
                    continue

                matched_law_names = [
                    law_name
                    for law_name in find_related_law_names(body_text, family_law_names)
                    if law_name and law_name != source["law_name"]
                ]
                article_refs = extract_explicit_article_refs(body_text, family_law_names)

                for target_law_name in matched_law_names:
                    target_law_uid = uid_by_name.get(target_law_name)
                    if not target_law_uid:
                        continue

                    target_article_refs = article_refs.get(target_law_name, [])
                    relation_type = "related_law" if target_article_refs else "cited_law"
                    article_keys = [item["article_key"] for item in target_article_refs]
                    article_no_displays = [item["article_no_display"] for item in target_article_refs]
                    relation_id = "::".join(
                        [
                            "relation",
                            "law",
                            source["law_uid"],
                            target_law_uid,
                            article_key or "root",
                        ]
                    )
                    current = merged.get(relation_id)
                    if current is None:
                        target_meta = law_meta_by_name[target_law_name]
                        current = {
                            "id": relation_id,
                            "canonical_id": relation_id,
                            "doc_type": "relation",
                            "source_group": "01_current_law",
                            "relation_model": "law_to_law",
                            "relation_type": relation_type,
                            "relation_types": [relation_type],
                            "law_name": target_law_name,
                            "law_uid": target_law_uid,
                            "source_law_name": source["law_name"],
                            "source_law_uid": source["law_uid"],
                            "root_law_name": root_law_name,
                            "root_law_uid": source["root_law_uid"],
                            "related_law_names": [target_law_name],
                            "article_keys": article_keys,
                            "article_no_displays": article_no_displays,
                            "relation_confidence": 0.95 if article_keys else 0.8,
                            "title": f"{source['law_name']} -> {target_law_name}",
                            "law_id": target_meta.get("law_id"),
                            "mst": target_meta.get("mst"),
                            "ef_yd": target_meta["payload"].get("ef_yd"),
                            "kind_name": target_meta["payload"].get("kind_name"),
                            "classified_level": target_meta["payload"].get("classified_level"),
                            "law_level": target_meta["payload"].get("classified_level"),
                            "source_hit_count": 1,
                            "section_type": "article",
                            "article_key": article_key or None,
                            "article_no_display": article.get("article_no_display") or article.get("article_no"),
                            "source_file_path": str(source["path"]),
                            "display_text": _truncate_text(body_text),
                        }
                        merged[relation_id] = current
                        continue

                    current["source_hit_count"] = int(current.get("source_hit_count") or 0) + 1
                    current["relation_confidence"] = max(
                        float(current.get("relation_confidence") or 0),
                        0.95 if article_keys else 0.8,
                    )
                    current["article_keys"] = list(dict.fromkeys(list(current.get("article_keys", [])) + article_keys))
                    current["article_no_displays"] = list(
                        dict.fromkeys(list(current.get("article_no_displays", [])) + article_no_displays)
                    )
                    current["relation_types"] = list(
                        dict.fromkeys(list(current.get("relation_types", [])) + [relation_type])
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
