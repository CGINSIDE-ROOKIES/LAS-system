from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

from src.common.io_utils import _safe_filename
from src.common.law_meta import build_law_uid
from src.export.legal_case_dataset_builder import (
    _iter_canonical_case_rows,
    _load_detail_payload,
    _merge_canonical_rows,
)
from src.parser.legal_case_parser import (
    build_evidence_preview,
    extract_case_number_refs,
    parse_case_payload,
)


def _normalize_case_number(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip()


def _build_case_to_case_text(record: dict[str, Any]) -> str:
    lines = [
        f"관계 모델: {record.get('relation_model') or ''}",
        f"관계 유형: {record.get('relation_type') or ''}",
        f"출발 문서 유형: {record.get('doc_type_label') or ''}",
        f"출발 문서 제목: {record.get('title') or ''}",
        f"출발 사건번호: {record.get('doc_number') or ''}",
        f"대상 문서 유형: {record.get('target_doc_type_label') or ''}",
        f"대상 문서 제목: {record.get('target_title') or ''}",
        f"대상 사건번호: {record.get('target_doc_number') or ''}",
    ]

    evidence_preview = str(record.get("evidence_preview") or "").strip()
    if evidence_preview:
        lines.append("근거 일부:")
        lines.append(evidence_preview)

    return "\n".join(line for line in lines if line).strip()


def _build_doc_number_index(canonical_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in canonical_rows:
        normalized_doc_number = _normalize_case_number(row.get("doc_number"))
        if normalized_doc_number:
            index[normalized_doc_number].append(row)
    return index


def _merge_referenced_case_numbers(
    parsed: dict[str, Any],
    body_text: str,
    source_doc_number: Any,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for item in parsed.get("structured_case_refs") or []:
        if not isinstance(item, dict):
            continue
        case_number = str(item.get("case_number") or "").strip()
        normalized = _normalize_case_number(case_number)
        if not normalized:
            continue
        entry = merged.setdefault(
            normalized,
            {
                "case_number": case_number,
                "reference_sources": [],
            },
        )
        if "structured_field" not in entry["reference_sources"]:
            entry["reference_sources"].append("structured_field")

    for case_number in extract_case_number_refs(body_text, exclude_numbers=[source_doc_number]):
        normalized = _normalize_case_number(case_number)
        if not normalized:
            continue
        entry = merged.setdefault(
            normalized,
            {
                "case_number": case_number,
                "reference_sources": [],
            },
        )
        if "body_regex" not in entry["reference_sources"]:
            entry["reference_sources"].append("body_regex")

    return [merged[key] for key in sorted(merged)]


def _iter_case_reference_candidates(
    raw_related_base_dir: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    canonical_rows = _merge_canonical_rows(list(_iter_canonical_case_rows(Path(raw_related_base_dir))))
    return canonical_rows, _build_doc_number_index(canonical_rows), canonical_rows


def _load_expc_related_prec_ids(row: dict[str, Any], base_dir: Path) -> list[str]:
    """expc HTML 수집 결과(sidecar JSON)에서 관련 prec ID를 로드한다."""
    canonical_case_id = str(
        row.get("canonical_case_id") or row.get("canonical_id") or row.get("id") or ""
    ).strip()
    if not canonical_case_id:
        return []
    root_dir = _safe_filename(str(row.get("root_law_name") or ""))
    safe_id = canonical_case_id.replace("::", "__").replace("/", "_")
    sidecar = base_dir / root_dir / "canonical" / "expc" / f"{safe_id}__related_prec_ids.json"
    if not sidecar.exists():
        return []
    try:
        import json
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return list(data.get("related_prec_ids") or [])
    except Exception:
        return []


def build_case_to_case_relation_records(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    skip_source_targets: set[str] | None = None,
    use_body_regex_fallback: bool = False,
) -> list[dict[str, Any]]:
    from src.parser.legal_case_parser import classify_case_type_from_number

    skip_targets = skip_source_targets or set()
    base_dir = Path(raw_related_base_dir)
    canonical_rows, doc_number_index, _ = _iter_case_reference_candidates(raw_related_base_dir)
    if not canonical_rows:
        return []

    # doc_id → canonical row 인덱스 (expc HTML prec_id 해결용)
    doc_id_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cr in canonical_rows:
        did = str(cr.get("doc_id") or "").strip()
        if did:
            doc_id_index[did].append(cr)

    records_by_id: dict[str, dict[str, Any]] = {}
    expc_mapping_stats: dict[str, int] = {"success": 0, "no_candidate": 0, "ambiguous": 0}

    for row in canonical_rows:
        source_canonical_case_id = str(
            row.get("canonical_case_id") or row.get("canonical_id") or row.get("id") or ""
        ).strip()
        if not source_canonical_case_id:
            continue

        source_target = str(row.get("target") or "").strip()
        if not source_target or source_target in skip_targets:
            continue

        # expc: HTML sidecar 기반 관계 추출
        if source_target == "expc":
            prec_ids = _load_expc_related_prec_ids(row, base_dir)
            for prec_id in prec_ids:
                candidates = [
                    c for c in doc_id_index.get(prec_id, [])
                    if str(c.get("target") or "").strip() in ("prec",)
                    and str(c.get("canonical_case_id") or c.get("canonical_id") or c.get("id") or "").strip()
                    != source_canonical_case_id
                ]
                if len(candidates) == 0:
                    expc_mapping_stats["no_candidate"] += 1
                    continue
                if len(candidates) > 1:
                    expc_mapping_stats["ambiguous"] += 1
                    continue
                expc_mapping_stats["success"] += 1
                target_row = candidates[0]
                target_cid = str(
                    target_row.get("canonical_case_id") or target_row.get("canonical_id") or target_row.get("id") or ""
                ).strip()
                if not target_cid:
                    continue
                relation_id = f"case_relation::{source_canonical_case_id}::{target_cid}"
                if relation_id in records_by_id:
                    continue
                record = {
                    "id": relation_id,
                    "canonical_id": source_canonical_case_id,
                    "canonical_case_id": source_canonical_case_id,
                    "source_canonical_case_id": source_canonical_case_id,
                    "target_canonical_case_id": target_cid,
                    "doc_type": "relation",
                    "doc_type_label": "법령해석례",
                    "source_group": "04_case_to_case_relations",
                    "relation_model": "case_to_case",
                    "relation_type": "cited_prec_html",
                    "relation_types": ["cited_prec_html"],
                    "relation_confidence": 0.92,
                    "resolution_status": "resolved",
                    "source_case_type": "expc",
                    "target_case_type": "prec",
                    "relation_subtype": "expc_to_prec",
                    "target": source_target,
                    "source_target": source_target,
                    "target_target": target_row.get("target"),
                    "title": row.get("title"),
                    "doc_id": row.get("doc_id"),
                    "doc_number": row.get("doc_number"),
                    "target_title": target_row.get("title"),
                    "target_doc_id": target_row.get("doc_id"),
                    "target_doc_number": target_row.get("doc_number"),
                    "target_doc_type_label": target_row.get("doc_type_label"),
                    "referenced_case_number": target_row.get("doc_number"),
                    "reference_sources": ["html_scraping"],
                    "root_law_name": row.get("root_law_name"),
                    "root_law_uid": build_law_uid(None, None, row.get("root_law_name")) if row.get("root_law_name") else None,
                    "root_law_names": row.get("root_law_names") or [],
                    "related_law_names": row.get("source_law_names") or [],
                    "source_law_name": (row.get("source_law_names") or [None])[0],
                    "source_law_names": row.get("source_law_names") or [],
                    "source_hit_count": row.get("source_hit_count"),
                    "source_file_path": row.get("detail_payload_path") or row.get("_canonical_index_path"),
                    "evidence_preview": "",
                }
                record["embedding_text"] = _build_case_to_case_text(record)
                record["text"] = record["embedding_text"]
                records_by_id[relation_id] = record
            continue

        # prec/detc: structured field 기반 관계 추출
        payload = _load_detail_payload(row)
        parsed = parse_case_payload(source_target, payload or {}, fallback=row)
        source_doc_number = parsed.get("doc_number") or row.get("doc_number")
        body_text = str(parsed.get("body_text") or "").strip()

        referenced_case_rows = _merge_referenced_case_numbers(
            parsed, body_text if use_body_regex_fallback else "", source_doc_number
        )
        if not referenced_case_rows:
            continue

        for ref_row in referenced_case_rows:
            referenced_case_number = str(ref_row.get("case_number") or "").strip()
            normalized_ref = _normalize_case_number(referenced_case_number)
            if not normalized_ref:
                continue

            candidate_rows = [
                candidate
                for candidate in doc_number_index.get(normalized_ref, [])
                if str(candidate.get("canonical_case_id") or candidate.get("canonical_id") or candidate.get("id") or "").strip()
                != source_canonical_case_id
            ]
            if len(candidate_rows) != 1:
                continue

            target_row = candidate_rows[0]
            target_canonical_case_id = str(
                target_row.get("canonical_case_id") or target_row.get("canonical_id") or target_row.get("id") or ""
            ).strip()
            if not target_canonical_case_id:
                continue

            target_case_type = str(target_row.get("target") or "").strip()
            if not target_case_type:
                target_case_type = classify_case_type_from_number(referenced_case_number) or ""

            relation_id = f"case_relation::{source_canonical_case_id}::{target_canonical_case_id}"
            if relation_id in records_by_id:
                continue

            relation_subtype = f"{source_target}_to_{target_case_type}" if target_case_type else None

            record = {
                "id": relation_id,
                "canonical_id": source_canonical_case_id,
                "canonical_case_id": source_canonical_case_id,
                "source_canonical_case_id": source_canonical_case_id,
                "target_canonical_case_id": target_canonical_case_id,
                "doc_type": "relation",
                "doc_type_label": parsed.get("doc_type_label"),
                "source_group": "04_case_to_case_relations",
                "relation_model": "case_to_case",
                "relation_type": "cited_case",
                "relation_types": ["cited_case"],
                "relation_confidence": 0.95,
                "resolution_status": "resolved",
                "source_case_type": source_target,
                "target_case_type": target_case_type,
                "relation_subtype": relation_subtype,
                "target": source_target,
                "source_target": source_target,
                "target_target": target_row.get("target"),
                "title": parsed.get("title"),
                "doc_id": parsed.get("doc_id"),
                "doc_number": source_doc_number,
                "doc_kind": parsed.get("doc_kind"),
                "detail_link": parsed.get("detail_link"),
                "decision_date": parsed.get("decision_date"),
                "target_title": target_row.get("title"),
                "target_doc_id": target_row.get("doc_id"),
                "target_doc_number": target_row.get("doc_number"),
                "target_doc_type_label": target_row.get("doc_type_label"),
                "referenced_case_number": referenced_case_number,
                "reference_sources": list(ref_row.get("reference_sources") or []),
                "root_law_name": row.get("root_law_name"),
                "root_law_uid": build_law_uid(None, None, row.get("root_law_name")) if row.get("root_law_name") else None,
                "root_law_names": row.get("root_law_names") or [],
                "related_law_names": row.get("source_law_names") or [],
                "source_law_name": (row.get("source_law_names") or [None])[0],
                "source_law_names": row.get("source_law_names") or [],
                "source_hit_count": row.get("source_hit_count"),
                "source_file_path": row.get("detail_payload_path") or row.get("_canonical_index_path"),
                "evidence_preview": build_evidence_preview(
                    body_text,
                    anchor=referenced_case_number,
                ),
            }
            record["embedding_text"] = _build_case_to_case_text(record)
            record["text"] = record["embedding_text"]
            records_by_id[relation_id] = record

    if any(expc_mapping_stats.values()):
        _log.info("expc->prec mapping stats: %s", expc_mapping_stats)

    rows = [records_by_id[key] for key in sorted(records_by_id)]
    return _dedup_bidirectional_c2c(rows)


def _dedup_bidirectional_c2c(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """case_to_case 양방향 중복(A→B, B→A)을 제거하고 한 방향만 유지한다.

    정렬된 (min_cid, max_cid) 쌍 기준으로 먼저 등장한 레코드를 보존한다.
    """
    seen_pairs: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        src = str(row.get("source_canonical_case_id") or "").strip()
        tgt = str(row.get("target_canonical_case_id") or "").strip()
        if not src or not tgt:
            deduped.append(row)
            continue
        canonical_pair = (min(src, tgt), max(src, tgt))
        if canonical_pair in seen_pairs:
            continue
        seen_pairs.add(canonical_pair)
        deduped.append(row)
    return deduped


def build_case_reference_audit_records(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    *,
    include_body_regex: bool = True,
) -> list[dict[str, Any]]:
    """audit 레코드를 생성한다.

    include_body_regex=True (기본): body_text 정규식 검색 포함 — 최대 커버리지
    include_body_regex=False: structured_field만 사용 — export graph(use_body_regex_fallback=False)와
                              동일 기준으로 비교할 때 사용
    """
    canonical_rows, doc_number_index, _ = _iter_case_reference_candidates(raw_related_base_dir)
    if not canonical_rows:
        return []

    audit_rows: list[dict[str, Any]] = []

    for row in canonical_rows:
        source_canonical_case_id = str(
            row.get("canonical_case_id") or row.get("canonical_id") or row.get("id") or ""
        ).strip()
        if not source_canonical_case_id:
            continue

        source_target = str(row.get("target") or "").strip()
        if not source_target:
            continue

        payload = _load_detail_payload(row)
        parsed = parse_case_payload(source_target, payload or {}, fallback=row)
        source_doc_number = parsed.get("doc_number") or row.get("doc_number")
        body_text = str(parsed.get("body_text") or "").strip()

        referenced_case_rows = _merge_referenced_case_numbers(
            parsed,
            body_text if include_body_regex else "",
            source_doc_number,
        )
        for ref_row in referenced_case_rows:
            referenced_case_number = str(ref_row.get("case_number") or "").strip()
            normalized_ref = _normalize_case_number(referenced_case_number)
            if not normalized_ref:
                continue

            candidate_rows = [
                candidate
                for candidate in doc_number_index.get(normalized_ref, [])
                if str(candidate.get("canonical_case_id") or candidate.get("canonical_id") or candidate.get("id") or "").strip()
                != source_canonical_case_id
            ]
            resolution_status = "resolved"
            target_canonical_case_ids: list[str] = []
            if not candidate_rows:
                resolution_status = "unresolved_external"
            elif len(candidate_rows) > 1:
                resolution_status = "ambiguous"
                target_canonical_case_ids = sorted(
                    {
                        str(candidate.get("canonical_case_id") or candidate.get("canonical_id") or candidate.get("id") or "").strip()
                        for candidate in candidate_rows
                        if str(candidate.get("canonical_case_id") or candidate.get("canonical_id") or candidate.get("id") or "").strip()
                    }
                )
            else:
                target_canonical_case_ids = [
                    str(candidate_rows[0].get("canonical_case_id") or candidate_rows[0].get("canonical_id") or candidate_rows[0].get("id") or "").strip()
                ]

            audit_rows.append(
                {
                    "id": f"case_ref_audit::{source_canonical_case_id}::{normalized_ref}",
                    "audit_type": "case_reference_resolution",
                    "audit_includes_body_regex": include_body_regex,
                    "source_canonical_case_id": source_canonical_case_id,
                    "source_target": source_target,
                    "source_title": parsed.get("title"),
                    "source_doc_number": source_doc_number,
                    "referenced_case_number": referenced_case_number,
                    "reference_sources": list(ref_row.get("reference_sources") or []),
                    "normalized_referenced_case_number": normalized_ref,
                    "resolution_status": resolution_status,
                    "candidate_count": len(candidate_rows),
                    "target_canonical_case_ids": target_canonical_case_ids,
                    "source_file_path": row.get("detail_payload_path") or row.get("_canonical_index_path"),
                    "evidence_preview": build_evidence_preview(body_text, anchor=referenced_case_number),
                }
            )

    audit_rows.sort(key=lambda row: str(row.get("id") or ""))
    return audit_rows
