from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Iterable


def canonical_id_from_row(row: dict) -> str:
    value = row.get("canonical_id") or row.get("canonical_case_id") or row.get("id")
    if value in (None, ""):
        raise ValueError("row.id or canonical_id is required")
    return str(value)


def point_id_context_digest(row: dict) -> str:
    basis = {
        "root_law_name": row.get("root_law_name"),
        "related_law_name": row.get("related_law_name"),
        "related_law_names": row.get("related_law_names"),
        "source_law_name": row.get("source_law_name"),
        "source_group": row.get("source_group"),
        "source_file_path": row.get("source_file_path"),
        "chunk_index": row.get("chunk_index"),
        "doc_id": row.get("doc_id"),
        "doc_number": row.get("doc_number"),
        "title": row.get("title"),
        "target": row.get("target"),
    }
    raw = json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()


def duplicate_canonical_ids(rows: Iterable[dict]) -> set[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter[canonical_id_from_row(row)] += 1
    return {canonical_id for canonical_id, count in counter.items() if count > 1}


def build_qdrant_point_id(row: dict, duplicate_ids: set[str] | None = None) -> str:
    duplicate_ids = duplicate_ids or set()
    canonical_id = canonical_id_from_row(row)
    if canonical_id not in duplicate_ids:
        return canonical_id
    return f"{canonical_id}::ctx::{point_id_context_digest(row)}"

