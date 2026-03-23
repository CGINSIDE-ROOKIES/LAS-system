from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from src.common.io_utils import _iter_jsonl, _read_json, _write_jsonl
from src.common.law_meta import build_law_uid
from src.parser.legal_case_parser import (
    build_evidence_preview,
    extract_case_number_refs,
    extract_explicit_article_refs,
    find_related_law_names,
    parse_case_payload,
)



def _iter_candidate_hit_rows(raw_related_base_dir: Path):
    for path in sorted(raw_related_base_dir.rglob("candidate_hits.jsonl")):
        root_law_name = path.parent.name.replace("_", " ").strip()
        for row in _iter_jsonl(path):
            row = dict(row)
            row.setdefault("root_law_name", root_law_name)
            row.setdefault("_candidate_hits_path", str(path))
            yield row



def _iter_canonical_case_rows(raw_related_base_dir: Path):
    for path in sorted(raw_related_base_dir.rglob("canonical_cases.jsonl")):
        root_law_name = path.parent.name.replace("_", " ").strip()
        for row in _iter_jsonl(path):
            row = dict(row)
            row.setdefault("root_law_name", root_law_name)
            row.setdefault("_canonical_index_path", str(path))
            yield row



def _load_detail_payload(row: dict[str, Any]) -> dict[str, Any]:
    detail_path = row.get("detail_payload_path")
    if detail_path in (None, ""):
        return {}
    path = Path(str(detail_path))
    if not path.exists():
        return {}
    return _read_json(path)



def _build_relation_text(record: dict[str, Any]) -> str:
    lines = [
        f"법령명: {record.get('law_name') or ''}",
        f"문서 유형: {record.get('doc_type_label') or ''}",
        f"문서 제목: {record.get('title') or ''}",
        f"문서 번호: {record.get('doc_number') or ''}",
        f"관계 유형: {', '.join(record.get('relation_types', []))}",
    ]

    article_displays = record.get("article_no_displays") or []
    if article_displays:
        lines.append(f"관련 조문: {', '.join(article_displays)}")

    referenced_case_numbers = record.get("referenced_case_numbers") or []
    if referenced_case_numbers:
        lines.append(f"참조 사건번호: {', '.join(referenced_case_numbers)}")

    evidence_preview = str(record.get("evidence_preview") or "").strip()
    if evidence_preview:
        lines.append("근거 일부:")
        lines.append(evidence_preview)

    return "\n".join(line for line in lines if line).strip()



def _confidence(
    article_refs: list[dict[str, str]],
    matched_law_names: list[str],
    law_name: str,
    referenced_case_numbers: list[str] | None = None,
) -> float:
    if article_refs:
        return 0.95
    if law_name in matched_law_names:
        return 0.85
    if referenced_case_numbers:
        return 0.75
    return 0.65



def build_root_relation_payloads(
    *,
    root_law_name: str,
    candidate_hits: list[dict[str, Any]],
    canonical_case_rows: list[dict[str, Any]],
    relation_rules: list[str] | None = None,
    targets: list[str] | None = None,
) -> list[dict[str, Any]]:
    relation_rules = relation_rules or ["related_law", "cited_law", "cited_case", "referenced_interpretation"]
    allowed_targets = set(targets) if targets else None

    candidate_hits = [
        row for row in candidate_hits
        if str(row.get("root_law_name") or "").strip() == root_law_name
        and (allowed_targets is None or row.get("target") in allowed_targets)
    ]
    canonical_case_rows = [
        row for row in canonical_case_rows
        if str(row.get("root_law_name") or "").strip() == root_law_name
        and (allowed_targets is None or row.get("target") in allowed_targets)
    ]

    canonical_map = {
        str(row.get("canonical_case_id") or row.get("canonical_id") or row.get("id") or "").strip(): row
        for row in canonical_case_rows
        if str(row.get("canonical_case_id") or row.get("canonical_id") or row.get("id") or "").strip()
    }

    relation_rows: list[dict[str, Any]] = []
    hits_by_case_and_law: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for hit in candidate_hits:
        canonical_case_id = str(hit.get("canonical_case_id") or hit.get("canonical_id") or "").strip()
        law_name = str(hit.get("source_law_name") or "").strip()
        if not canonical_case_id or not law_name:
            continue
        hits_by_case_and_law[(canonical_case_id, law_name)].append(hit)

    for (canonical_case_id, law_name), hits in sorted(hits_by_case_and_law.items()):
        canonical_row = canonical_map.get(canonical_case_id)
        target = str(hits[0].get("target") or (canonical_row or {}).get("target") or "").strip()
        if not target:
            continue

        payload = _load_detail_payload(canonical_row or {})
        parsed = parse_case_payload(target, payload or {}, fallback=canonical_row or hits[0])
        body_text = str(parsed.get("body_text") or "").strip()

        family_law_names = sorted(
            {
                str(hit.get("source_law_name") or "").strip()
                for hit in candidate_hits
                if str(hit.get("source_law_name") or "").strip()
            }
        )
        matched_law_names = find_related_law_names(body_text, family_law_names) if body_text else []
        article_refs_map = extract_explicit_article_refs(body_text, family_law_names) if body_text else {}
        article_refs = article_refs_map.get(law_name, [])
        referenced_case_numbers = extract_case_number_refs(
            body_text,
            exclude_numbers=[parsed.get("doc_number")],
        ) if body_text else []

        relation_types: list[str] = ["search_hit"]
        if law_name in matched_law_names and "cited_law" in relation_rules:
            relation_types.append("cited_law")
        if article_refs and "related_law" in relation_rules:
            relation_types.append("related_law")
        if referenced_case_numbers and "cited_case" in relation_rules:
            relation_types.append("cited_case")

        relation_types = list(dict.fromkeys(relation_types))
        source_law_uid = str(hits[0].get("source_law_uid") or build_law_uid(None, None, law_name))
        preview_anchor = law_name if law_name in matched_law_names else (referenced_case_numbers[0] if referenced_case_numbers else None)
        evidence_preview = build_evidence_preview(body_text, law_name=law_name, anchor=preview_anchor)
        article_keys = [item["article_key"] for item in article_refs]
        article_no_displays = [item["article_no_display"] for item in article_refs]

        relation_row = {
            "id": f"relation::{canonical_case_id}::{source_law_uid}",
            "canonical_case_id": canonical_case_id,
            "canonical_id": canonical_case_id,
            "law_uid": source_law_uid,
            "law_name": law_name,
            "root_law_name": root_law_name,
            "matched_query_law_name": law_name,
            "doc_type": "relation",
            "doc_type_label": parsed.get("doc_type_label"),
            "source_group": "03_expanded_related_docs",
            "target": target,
            "title": parsed.get("title"),
            "doc_id": parsed.get("doc_id"),
            "doc_number": parsed.get("doc_number"),
            "doc_kind": parsed.get("doc_kind"),
            "detail_link": parsed.get("detail_link"),
            "decision_date": parsed.get("decision_date"),
            "source_law_name": law_name,
            "related_law_names": [law_name],
            "relation_types": relation_types,
            "article_keys": article_keys,
            "article_no_displays": article_no_displays,
            "referenced_case_numbers": referenced_case_numbers,
            "relation_confidence": _confidence(article_refs, matched_law_names, law_name, referenced_case_numbers),
            "evidence_preview": evidence_preview,
            "source_hit_count": len(hits),
            "source_file_paths": sorted(
                {
                    str(hit.get("source_file_path") or "").strip()
                    for hit in hits
                    if str(hit.get("source_file_path") or "").strip()
                }
            ),
        }
        relation_row["embedding_text"] = _build_relation_text(relation_row)
        relation_row["text"] = relation_row["embedding_text"]
        relation_rows.append(relation_row)

    return relation_rows



def _merge_relation_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue

        current = merged.get(row_id)
        if current is None:
            current = dict(row)
            current["root_law_names"] = set([str(row.get("root_law_name") or "").strip()]) if row.get("root_law_name") else set()
            current["relation_types"] = list(dict.fromkeys(row.get("relation_types", [])))
            current["article_keys"] = list(dict.fromkeys(row.get("article_keys", [])))
            current["article_no_displays"] = list(dict.fromkeys(row.get("article_no_displays", [])))
            current["referenced_case_numbers"] = list(dict.fromkeys(row.get("referenced_case_numbers", [])))
            current["source_file_paths"] = list(dict.fromkeys(row.get("source_file_paths", [])))
            merged[row_id] = current
            continue

        current["source_hit_count"] = int(current.get("source_hit_count") or 0) + int(row.get("source_hit_count") or 0)
        if row.get("root_law_name"):
            current["root_law_names"].add(str(row.get("root_law_name")).strip())
        current["relation_types"] = list(dict.fromkeys(list(current.get("relation_types", [])) + list(row.get("relation_types", []))))
        current["article_keys"] = list(dict.fromkeys(list(current.get("article_keys", [])) + list(row.get("article_keys", []))))
        current["article_no_displays"] = list(dict.fromkeys(list(current.get("article_no_displays", [])) + list(row.get("article_no_displays", []))))
        current["referenced_case_numbers"] = list(dict.fromkeys(list(current.get("referenced_case_numbers", [])) + list(row.get("referenced_case_numbers", []))))
        current["source_file_paths"] = list(dict.fromkeys(list(current.get("source_file_paths", [])) + list(row.get("source_file_paths", []))))
        current["relation_confidence"] = max(float(current.get("relation_confidence") or 0), float(row.get("relation_confidence") or 0))
        if not current.get("evidence_preview") and row.get("evidence_preview"):
            current["evidence_preview"] = row.get("evidence_preview")

    results: list[dict[str, Any]] = []
    for current in merged.values():
        current["root_law_names"] = sorted(item for item in current["root_law_names"] if item)
        current["text"] = _build_relation_text(current)
        current["embedding_text"] = current["text"]
        results.append(current)

    results.sort(key=lambda row: str(row.get("id") or ""))
    return results



def build_legal_relation_records(
    expanded_base_dir: str | Path = "data/expanded/03_expanded_related_docs",
    raw_related_base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    expanded_dir = Path(expanded_base_dir)
    rows: list[dict[str, Any]] = []

    for path in sorted(expanded_dir.rglob("relation_records.jsonl")):
        rows.extend(list(_iter_jsonl(path)))

    if rows:
        return _merge_relation_rows(rows)

    if raw_related_base_dir is None:
        return []

    raw_dir = Path(raw_related_base_dir)
    candidate_hits = list(_iter_candidate_hit_rows(raw_dir))
    canonical_rows = list(_iter_canonical_case_rows(raw_dir))
    if not candidate_hits or not canonical_rows:
        return []

    root_law_names = sorted(
        {
            str(row.get("root_law_name") or "").strip()
            for row in candidate_hits
            if str(row.get("root_law_name") or "").strip()
        }
    )

    built_rows: list[dict[str, Any]] = []
    for root_law_name in root_law_names:
        built_rows.extend(
            build_root_relation_payloads(
                root_law_name=root_law_name,
                candidate_hits=candidate_hits,
                canonical_case_rows=canonical_rows,
            )
        )

    return _merge_relation_rows(built_rows)



def write_relation_records(path: str | Path, rows: list[dict[str, Any]]) -> None:
    _write_jsonl(Path(path), rows)
