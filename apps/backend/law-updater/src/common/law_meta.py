from __future__ import annotations

import ast
import re
from typing import Any


def _clean_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _safe_literal_dict(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text or not (text.startswith("{") and text.endswith("}")):
        return None

    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None

    return parsed if isinstance(parsed, dict) else None


def normalize_kind_name(value: Any) -> str | None:
    if value in (None, ""):
        return None

    if isinstance(value, dict):
        for key in ("content", "법종구분명", "법종명", "value", "text", "name"):
            candidate = _clean_text(value.get(key))
            if candidate:
                return candidate
        return None

    text = _clean_text(value)
    if not text:
        return None

    parsed_dict = _safe_literal_dict(text)
    if parsed_dict:
        normalized = normalize_kind_name(parsed_dict)
        if normalized:
            return normalized

    return text


def classify_law_level(kind_name: str | None) -> str:
    text = _clean_text(kind_name)

    if "법률" in text or text == "법":
        return "법"
    if "대통령령" in text or "시행령" in text:
        return "시행령"
    if "부령" in text or "시행규칙" in text or "규칙" in text:
        return "시행규칙"

    return text or "기타"


def normalize_classified_level(
    kind_name: Any,
    existing: Any = None,
) -> str:
    normalized_kind = normalize_kind_name(kind_name)
    normalized_existing = _clean_text(existing)

    classified = classify_law_level(normalized_kind or normalized_existing)
    if classified == "기타" and normalized_existing:
        return normalized_existing
    return classified


def normalize_identifier_token(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return "unknown"

    text = text.replace("::", "-")
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[\\/]+", "-", text)
    return text


def build_law_uid(
    law_id: Any,
    mst: Any,
    law_name: Any,
) -> str:
    for candidate in (law_id, mst, law_name):
        text = _clean_text(candidate)
        if text:
            return normalize_identifier_token(text)
    return "unknown-law"


def build_strict_law_uid(
    law_id: Any,
    mst: Any,
) -> str | None:
    for candidate in (law_id, mst):
        text = _clean_text(candidate)
        if text:
            return normalize_identifier_token(text)
    return None


def build_record_id(
    *,
    prefix: str,
    law_id: Any,
    mst: Any,
    law_name: Any,
    section_type: str,
    section_uid: Any,
    chunk_index: int,
) -> str:
    return "::".join(
        [
            normalize_identifier_token(prefix),
            build_law_uid(law_id, mst, law_name),
            normalize_identifier_token(section_type),
            normalize_identifier_token(section_uid),
            str(chunk_index),
        ]
    )
