from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.collector.legal_doc_collector import DOC_TYPE_LABELS
from src.common.law_meta import build_law_uid
from src.common.io_utils import _iter_jsonl, _read_json
from src.parser.legal_case_parser import parse_case_payload



def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()



def _normalize_structure(text: str) -> str:
    normalized_lines: list[str] = []
    previous_blank = False

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", raw_line).strip()
        if not line:
            if normalized_lines and not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(line)
        previous_blank = False

    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()

    return "\n".join(normalized_lines).strip()



def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    text = _normalize_structure(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            split_candidates = [
                text.rfind("\n", start, end),
                text.rfind(". ", start, end),
                text.rfind("。", start, end),
                text.rfind(" ", start, end),
            ]
            split = max(split_candidates)
            if split > start + (max_chars // 2):
                end = split + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break
        start = max(0, end - overlap)

    return chunks


def _truncate_text(text: str, limit: int = 320) -> str:
    normalized = _normalize_space(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"



def _iter_canonical_case_rows(raw_related_base_dir: Path):
    for path in sorted(raw_related_base_dir.rglob("canonical_cases.jsonl")):
        for row in _iter_jsonl(path):
            row = dict(row)
            row.setdefault("_canonical_index_path", str(path))
            yield row



def _merge_canonical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _to_clean_set(value: Any) -> set[str]:
        if value is None:
            return set()
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip() for item in value if str(item).strip()}
        text = str(value).strip()
        return {text} if text else set()

    merged: dict[str, dict[str, Any]] = {}

    for row in rows:
        canonical_case_id = str(
            row.get("canonical_case_id") or row.get("canonical_id") or row.get("id") or ""
        ).strip()
        if not canonical_case_id:
            continue

        current = merged.get(canonical_case_id)
        if current is None:
            current = dict(row)
            current["root_law_names"] = _to_clean_set(row.get("root_law_names"))
            if row.get("root_law_name"):
                current["root_law_names"].add(str(row.get("root_law_name")).strip())

            current["source_law_names"] = _to_clean_set(row.get("source_law_names"))
            current["source_law_uids"] = _to_clean_set(row.get("source_law_uids"))
            current["source_hit_count"] = int(row.get("source_hit_count") or 0)

            merged[canonical_case_id] = current
            continue

        current["source_hit_count"] = int(current.get("source_hit_count") or 0) + int(
            row.get("source_hit_count") or 0
        )

        current["root_law_names"] = _to_clean_set(current.get("root_law_names"))
        current["source_law_names"] = _to_clean_set(current.get("source_law_names"))
        current["source_law_uids"] = _to_clean_set(current.get("source_law_uids"))

        if row.get("root_law_name"):
            current["root_law_names"].add(str(row.get("root_law_name")).strip())

        current["root_law_names"].update(_to_clean_set(row.get("root_law_names")))
        current["source_law_names"].update(_to_clean_set(row.get("source_law_names")))
        current["source_law_uids"].update(_to_clean_set(row.get("source_law_uids")))

        if not bool(current.get("detail_available")) and bool(row.get("detail_available")):
            preserved_root_law_names = set(current["root_law_names"])
            preserved_source_law_names = set(current["source_law_names"])
            preserved_source_law_uids = set(current["source_law_uids"])
            preserved_source_hit_count = int(current.get("source_hit_count") or 0)

            for key, value in row.items():
                current[key] = value

            current["root_law_names"] = preserved_root_law_names
            current["source_law_names"] = preserved_source_law_names
            current["source_law_uids"] = preserved_source_law_uids
            current["source_hit_count"] = preserved_source_hit_count

    results: list[dict[str, Any]] = []
    for current in merged.values():
        current["canonical_case_id"] = str(
            current.get("canonical_case_id") or current.get("canonical_id") or current.get("id")
        )
        current["canonical_id"] = current["canonical_case_id"]
        current["root_law_names"] = sorted(item for item in _to_clean_set(current.get("root_law_names")) if item)
        current["source_law_names"] = sorted(item for item in _to_clean_set(current.get("source_law_names")) if item)
        current["source_law_uids"] = sorted(item for item in _to_clean_set(current.get("source_law_uids")) if item)
        results.append(current)

    results.sort(key=lambda row: (str(row.get("target") or ""), str(row.get("canonical_case_id") or "")))
    return results


def _load_detail_payload(row: dict[str, Any]) -> dict[str, Any]:
    detail_path = row.get("detail_payload_path")
    if detail_path in (None, ""):
        return {}
    path = Path(str(detail_path))
    if not path.exists():
        return {}
    return _read_json(path)



def _build_case_text(parsed: dict[str, Any], row: dict[str, Any]) -> str:
    target = str(parsed.get("target") or row.get("target") or "").strip()
    source_law_names = row.get("source_law_names") or []
    lines = [f"문서 유형: {DOC_TYPE_LABELS.get(target, target)}"]

    if parsed.get("title"):
        lines.append(f"문서 제목: {parsed['title']}")
    if parsed.get("doc_number"):
        lines.append(f"문서 번호: {parsed['doc_number']}")
    if parsed.get("decision_date"):
        lines.append(f"결정/선고일: {parsed['decision_date']}")
    if source_law_names:
        lines.append(f"관련 법령 검색 hit: {', '.join(source_law_names)}")

    body_text = str(parsed.get("body_text") or "").strip()
    if body_text:
        lines.append(body_text)

    return "\n".join(line for line in lines if line).strip()



def build_legal_case_records(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    max_chars: int = 1200,
    overlap: int = 150,
) -> list[dict[str, Any]]:
    base_dir = Path(raw_related_base_dir)
    canonical_rows = _merge_canonical_rows(list(_iter_canonical_case_rows(base_dir)))
    if not canonical_rows:
        return []

    records: list[dict[str, Any]] = []

    for row in canonical_rows:
        target = str(row.get("target") or "").strip()
        if not target:
            continue

        payload = _load_detail_payload(row)
        parsed = parse_case_payload(target, payload or {}, fallback=row)
        full_text = _build_case_text(parsed, row)
        chunks = _chunk_text(full_text, max_chars=max_chars, overlap=overlap)
        if not chunks and full_text:
            chunks = [full_text]
        if not chunks:
            continue

        canonical_case_id = str(row.get("canonical_case_id") or parsed.get("canonical_case_id") or "").strip()
        if not canonical_case_id:
            continue

        related_law_names = list(row.get("source_law_names") or [])
        root_law_names = list(row.get("root_law_names") or [])
        source_law_uids = list(row.get("source_law_uids") or [])
        first_related_law_name = related_law_names[0] if related_law_names else None
        first_root_law_name = root_law_names[0] if root_law_names else row.get("root_law_name")
        first_source_law_uid = source_law_uids[0] if source_law_uids else None
        root_law_uid = build_law_uid(None, None, first_root_law_name)

        for chunk_index, chunk in enumerate(chunks):
            search_parts = [
                DOC_TYPE_LABELS.get(target, target),
                parsed.get("title"),
                parsed.get("doc_number"),
                first_related_law_name,
                chunk,
            ]
            search_text = "\n".join(str(item).strip() for item in search_parts if str(item or "").strip()).strip()
            display_text = "\n".join(
                part
                for part in (
                    str(parsed.get("title") or "").strip(),
                    str(parsed.get("doc_number") or "").strip(),
                    _truncate_text(chunk),
                )
                if part
            ).strip()
            records.append(
                {
                    "id": f"case_chunk::{canonical_case_id}::{chunk_index}",
                    "canonical_id": canonical_case_id,
                    "canonical_case_id": canonical_case_id,
                    "text": chunk,
                    "search_text": search_text or chunk,
                    "display_text": display_text or _truncate_text(chunk),
                    "doc_type": target,
                    "doc_type_label": DOC_TYPE_LABELS.get(target, target),
                    "source_group": "02_related_legal_docs",
                    "root_law_name": first_root_law_name,
                    "root_law_uid": root_law_uid,
                    "root_law_names": root_law_names,
                    "related_law_name": first_related_law_name,
                    "related_law_names": related_law_names,
                    "source_law_name": first_related_law_name,
                    "source_law_uid": first_source_law_uid,
                    "source_law_uids": source_law_uids,
                    "source_law_names": related_law_names,
                    "title": parsed.get("title"),
                    "doc_id": parsed.get("doc_id"),
                    "doc_number": parsed.get("doc_number"),
                    "doc_kind": parsed.get("doc_kind"),
                    "detail_link": parsed.get("detail_link"),
                    "decision_date": parsed.get("decision_date"),
                    "target": target,
                    "chunk_index": chunk_index,
                    "source_file_path": row.get("detail_payload_path") or row.get("_canonical_index_path"),
                    "source_hit_count": row.get("source_hit_count"),
                }
            )

    return records
