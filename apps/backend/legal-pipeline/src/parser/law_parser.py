from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from src.common.io_utils import _safe_filename, _write_json
from src.common.payload_utils import _first_non_empty, _walk_objects

ARTICLE_CODE_KEYS = ("JO", "조문번호키", "jo_code")
ARTICLE_NO_KEYS = ("조문번호", "조번호", "article_no")
ARTICLE_TITLE_KEYS = ("조문제목", "조제목", "article_title")
ARTICLE_TEXT_KEYS = ("조문내용", "article_text")

PARAGRAPH_CODE_KEYS = ("HANG", "항번호키", "hang_code")
PARAGRAPH_NO_KEYS = ("항번호", "paragraph_no")
PARAGRAPH_TEXT_KEYS = ("항내용", "paragraph_text", "내용")

ITEM_CODE_KEYS = ("HO", "호번호키", "ho_code")
ITEM_NO_KEYS = ("호번호", "item_no")
ITEM_TEXT_KEYS = ("호내용", "item_text", "내용")

SUBITEM_CODE_KEYS = ("MOK", "목번호키", "mok_code")
SUBITEM_NO_KEYS = ("목번호", "subitem_no")
SUBITEM_TEXT_KEYS = ("목내용", "subitem_text", "내용")

SUPPLEMENTARY_NO_KEYS = ("부칙번호", "부칙조번호", "supplementary_no")
SUPPLEMENTARY_TITLE_KEYS = ("부칙제목", "제목", "supplementary_title")
SUPPLEMENTARY_TEXT_KEYS = ("부칙내용", "내용", "본문", "supplementary_text")

APPENDIX_TITLE_KEYS = (
    "별표제목",
    "별표명",
    "서식명",
    "서식제목",
    "제목",
    "명칭",
    "appendix_title",
)
APPENDIX_TEXT_KEYS = (
    "별표내용",
    "서식내용",
    "내용",
    "본문",
    "텍스트",
    "appendix_text",
)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _coerce_text(value: Any) -> str | None:
    if value in (None, ""):
        return None

    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None

    return text


def _normalize_text_preserve_structure(value: Any) -> str | None:
    text = _coerce_text(value)
    if text is None:
        return None

    normalized_lines: list[str] = []
    prev_blank = False

    for raw_line in text.split("\n"):
        line = re.sub(r"[\t\f\v ]+", " ", raw_line).strip()
        if not line:
            if not prev_blank:
                normalized_lines.append("")
            prev_blank = True
            continue

        normalized_lines.append(line)
        prev_blank = False

    while normalized_lines and normalized_lines[0] == "":
        normalized_lines.pop(0)
    while normalized_lines and normalized_lines[-1] == "":
        normalized_lines.pop()

    normalized = "\n".join(normalized_lines).strip()
    return normalized or None


def _normalize_text_flat(value: Any) -> str | None:
    text = _coerce_text(value)
    if text is None:
        return None

    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized or None


# backward-compatible helper for code that still expects the previous flat normalizer

def _normalize_text(value: Any) -> str | None:
    return _normalize_text_flat(value)


def _dedup_texts(values: Iterable[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for value in values:
        dedup_key = _normalize_text_flat(value)
        if dedup_key is None or dedup_key in seen:
            continue

        structured = _normalize_text_preserve_structure(value)
        if structured is None:
            continue

        seen.add(dedup_key)
        results.append(structured)

    return results


def _walk_strings(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)
    elif isinstance(node, str):
        text = _coerce_text(node)
        if text:
            yield text


def _join_nested_text(node: Any, *, exclude_strings: Iterable[str] = ()) -> str | None:
    excluded = {
        normalized
        for value in exclude_strings
        for normalized in [_normalize_text_flat(value)]
        if normalized
    }
    texts = [text for text in _dedup_texts(_walk_strings(node)) if _normalize_text_flat(text) not in excluded]
    if not texts:
        return None
    return "\n".join(texts)


def _extract_text_pair(
    mapping: dict[str, Any],
    keys: tuple[str, ...],
    *,
    fallback_to_nested: bool = False,
    exclude_strings: Iterable[str] = (),
) -> tuple[str | None, str | None]:
    raw = _coerce_text(_first_non_empty(mapping, *keys))
    if raw is None and fallback_to_nested:
        raw = _join_nested_text(mapping, exclude_strings=exclude_strings)

    if raw is None:
        return None, None

    return raw, _normalize_text_preserve_structure(raw)


def get_law_root(payload: dict[str, Any]) -> dict[str, Any]:
    law_root = payload.get("법령")
    if not isinstance(law_root, dict):
        raise ValueError("law body payload must contain dict key '법령'")
    return law_root


def _extract_container_units(
    container: Any,
    preferred_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    if container is None:
        return []

    if isinstance(container, list):
        return [item for item in container if isinstance(item, dict)]

    if isinstance(container, dict):
        for key in preferred_keys:
            value = container.get(key)
            units = [item for item in _as_list(value) if isinstance(item, dict)]
            if units:
                return units

        return [container]

    return []


def get_article_units(law_root: dict[str, Any]) -> list[dict[str, Any]]:
    article_container = law_root.get("조문")

    units = _extract_container_units(
        article_container,
        ("조문단위", "조문", "article"),
    )
    if units:
        return units

    fallback: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for obj in _walk_objects(law_root):
        jo_code = _first_non_empty(obj, *ARTICLE_CODE_KEYS)
        article_no = _first_non_empty(obj, *ARTICLE_NO_KEYS)
        article_title = _first_non_empty(obj, *ARTICLE_TITLE_KEYS)

        if jo_code is None and article_no is None and article_title is None:
            continue

        key = (
            str(jo_code or ""),
            str(article_no or ""),
            str(article_title or ""),
        )
        if key in seen:
            continue

        seen.add(key)
        fallback.append(obj)

    return fallback


def get_paragraph_units(article_unit: dict[str, Any]) -> list[dict[str, Any]]:
    units = _extract_container_units(
        article_unit.get("항"),
        ("항단위", "항", "paragraph"),
    )
    if units:
        return units

    fallback: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for obj in _walk_objects(article_unit):
        if any(key in obj for key in ARTICLE_CODE_KEYS + ARTICLE_NO_KEYS):
            continue

        hang_code = _first_non_empty(obj, *PARAGRAPH_CODE_KEYS)
        paragraph_no = _first_non_empty(obj, *PARAGRAPH_NO_KEYS)

        if hang_code is None and paragraph_no is None:
            continue

        key = (str(hang_code or ""), str(paragraph_no or ""))
        if key in seen:
            continue

        seen.add(key)
        fallback.append(obj)

    return fallback


def get_item_units(paragraph_unit: dict[str, Any]) -> list[dict[str, Any]]:
    units = _extract_container_units(
        paragraph_unit.get("호"),
        ("호단위", "호", "item"),
    )
    if units:
        return units

    fallback: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for obj in _walk_objects(paragraph_unit):
        ho_code = _first_non_empty(obj, *ITEM_CODE_KEYS)
        item_no = _first_non_empty(obj, *ITEM_NO_KEYS)

        if ho_code is None and item_no is None:
            continue

        key = (str(ho_code or ""), str(item_no or ""))
        if key in seen:
            continue

        seen.add(key)
        fallback.append(obj)

    return fallback


def get_subitem_units(item_unit: dict[str, Any]) -> list[dict[str, Any]]:
    units = _extract_container_units(
        item_unit.get("목"),
        ("목단위", "목", "subitem"),
    )
    if units:
        return units

    fallback: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for obj in _walk_objects(item_unit):
        mok_code = _first_non_empty(obj, *SUBITEM_CODE_KEYS)
        subitem_no = _first_non_empty(obj, *SUBITEM_NO_KEYS)

        if mok_code is None and subitem_no is None:
            continue

        key = (str(mok_code or ""), str(subitem_no or ""))
        if key in seen:
            continue

        seen.add(key)
        fallback.append(obj)

    return fallback


def parse_subitem_unit(item_unit: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for unit in get_subitem_units(item_unit):
        raw_text, normalized_text = _extract_text_pair(unit, SUBITEM_TEXT_KEYS)
        results.append(
            {
                "mok_code": _first_non_empty(unit, *SUBITEM_CODE_KEYS),
                "subitem_no": _first_non_empty(unit, *SUBITEM_NO_KEYS),
                "subitem_text_raw": raw_text,
                "subitem_text": normalized_text,
            }
        )

    return results


def parse_item_unit(paragraph_unit: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for unit in get_item_units(paragraph_unit):
        raw_text, normalized_text = _extract_text_pair(unit, ITEM_TEXT_KEYS)
        results.append(
            {
                "ho_code": _first_non_empty(unit, *ITEM_CODE_KEYS),
                "item_no": _first_non_empty(unit, *ITEM_NO_KEYS),
                "item_text_raw": raw_text,
                "item_text": normalized_text,
                "subitems": parse_subitem_unit(unit),
            }
        )

    return results


def parse_paragraph_unit(article_unit: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for unit in get_paragraph_units(article_unit):
        raw_text, normalized_text = _extract_text_pair(unit, PARAGRAPH_TEXT_KEYS)
        results.append(
            {
                "hang_code": _first_non_empty(unit, *PARAGRAPH_CODE_KEYS),
                "paragraph_no": _first_non_empty(unit, *PARAGRAPH_NO_KEYS),
                "paragraph_text_raw": raw_text,
                "paragraph_text": normalized_text,
                "items": parse_item_unit(unit),
            }
        )

    return results


def parse_article_unit(article_unit: dict[str, Any]) -> dict[str, Any]:
    article_title_raw, article_title = _extract_text_pair(article_unit, ARTICLE_TITLE_KEYS)
    article_text_raw, article_text = _extract_text_pair(article_unit, ARTICLE_TEXT_KEYS)

    return {
        "jo_code": _first_non_empty(article_unit, *ARTICLE_CODE_KEYS),
        "article_no": _first_non_empty(article_unit, *ARTICLE_NO_KEYS),
        "article_title_raw": article_title_raw,
        "article_title": article_title,
        "article_text_raw": article_text_raw,
        "article_text": article_text,
        "paragraphs": parse_paragraph_unit(article_unit),
    }


def _extract_supplementary_units(law_root: dict[str, Any]) -> list[dict[str, Any]]:
    container = law_root.get("부칙")
    units = _extract_container_units(
        container,
        ("부칙단위", "부칙조문", "조문단위", "supplementary"),
    )
    if units:
        return units

    fallback: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for obj in _walk_objects(law_root):
        title = _first_non_empty(obj, *SUPPLEMENTARY_TITLE_KEYS)
        text = _first_non_empty(obj, *SUPPLEMENTARY_TEXT_KEYS)

        if title is None and text is None:
            continue

        combined = f"{title or ''} {text or ''}"
        if "부칙" not in str(combined):
            continue

        key = (str(title or ""), str(text or ""))
        if key in seen:
            continue
        seen.add(key)
        fallback.append(obj)

    return fallback


def _parse_supplementary_unit(unit: dict[str, Any]) -> dict[str, Any]:
    title_raw = _coerce_text(_first_non_empty(unit, *SUPPLEMENTARY_TITLE_KEYS)) or "부칙"
    title = _normalize_text_preserve_structure(title_raw) or "부칙"
    text_raw, text = _extract_text_pair(
        unit,
        SUPPLEMENTARY_TEXT_KEYS,
        fallback_to_nested=True,
        exclude_strings=[title_raw],
    )

    return {
        "supplementary_no": _first_non_empty(unit, *SUPPLEMENTARY_NO_KEYS),
        "supplementary_title_raw": title_raw,
        "supplementary_title": title,
        "supplementary_text_raw": text_raw,
        "supplementary_text": text,
    }


def parse_supplementary(law_root: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for unit in _extract_supplementary_units(law_root):
        parsed = _parse_supplementary_unit(unit)
        if parsed["supplementary_text"] in (None, ""):
            continue
        results.append(parsed)
    return results


def _iter_appendix_candidates(law_root: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for obj in _walk_objects(law_root):
        if not isinstance(obj, dict):
            continue

        yield obj

        for key, value in obj.items():
            key_text = str(key)
            if key_text in APPENDIX_TITLE_KEYS or key_text in APPENDIX_TEXT_KEYS:
                continue
            if any(token in key_text for token in ("별표", "별지", "서식")):
                if isinstance(value, dict):
                    synthetic = dict(value)
                    synthetic.setdefault("_synthetic_title", key_text)
                    yield synthetic
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            synthetic = dict(item)
                            synthetic.setdefault("_synthetic_title", key_text)
                            yield synthetic
                        elif isinstance(item, str):
                            yield {
                                "_synthetic_title": key_text,
                                "_synthetic_text": item,
                            }
                elif isinstance(value, str):
                    yield {
                        "_synthetic_title": key_text,
                        "_synthetic_text": value,
                    }


def _matches_part_policy(
    title: str,
    include_parts: list[str],
    exclude_parts: list[str],
) -> tuple[bool, bool]:
    include_hit = True if not include_parts else any(part in title for part in include_parts)
    exclude_hit = any(part in title for part in exclude_parts)
    return include_hit, exclude_hit


def parse_appendices(
    law_root: dict[str, Any],
    *,
    include_parts: list[str] | None = None,
    exclude_parts: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    include_parts = include_parts or []
    exclude_parts = exclude_parts or []

    appendices: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for candidate in _iter_appendix_candidates(law_root):
        title_raw = _coerce_text(_first_non_empty(candidate, *APPENDIX_TITLE_KEYS))
        if title_raw is None:
            title_raw = _coerce_text(candidate.get("_synthetic_title"))

        if title_raw is None:
            continue

        title = _normalize_text_preserve_structure(title_raw)
        if title is None:
            continue

        if not any(token in title for token in ("별표", "별지", "서식")):
            continue

        text_raw, text = _extract_text_pair(
            candidate,
            APPENDIX_TEXT_KEYS,
            fallback_to_nested=True,
            exclude_strings=[title_raw],
        )
        if text is None:
            continue

        include_hit, exclude_hit = _matches_part_policy(title, include_parts, exclude_parts)
        if not include_hit and not exclude_hit:
            continue

        record = {
            "appendix_title_raw": title_raw,
            "appendix_title": title,
            "appendix_text_raw": text_raw,
            "appendix_text": text,
            "excluded": exclude_hit,
        }
        dedup_key = (title, text)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        if exclude_hit:
            excluded.append(record)
        else:
            appendices.append(record)

    return appendices, excluded


def parse_law_body(
    payload: dict[str, Any],
    law_ref: dict[str, Any] | None = None,
    *,
    include_parts: list[str] | None = None,
    exclude_parts: list[str] | None = None,
) -> dict[str, Any]:
    law_root = get_law_root(payload)
    article_units = get_article_units(law_root)

    articles = [parse_article_unit(unit) for unit in article_units]
    supplementary = parse_supplementary(law_root)
    appendices, excluded_appendices = parse_appendices(
        law_root,
        include_parts=include_parts,
        exclude_parts=exclude_parts,
    )

    include_parts = include_parts or []
    exclude_parts = exclude_parts or []

    return {
        "law_name": (law_ref or {}).get("law_name")
        or _first_non_empty(law_root, "법령명한글", "법령명"),
        "law_id": (law_ref or {}).get("law_id")
        or _first_non_empty(law_root, "법령ID", "law_id"),
        "mst": (law_ref or {}).get("mst")
        or _first_non_empty(law_root, "법령일련번호", "mst"),
        "ef_yd": (law_ref or {}).get("ef_yd")
        or _first_non_empty(law_root, "시행일자", "ef_yd"),
        "kind_name": (law_ref or {}).get("kind_name")
        or _first_non_empty(law_root, "법령구분명", "법종구분명", "kind_name"),
        "classified_level": (law_ref or {}).get("classified_level"),
        "scope_source": (law_ref or {}).get("scope_source"),
        "articles_count": len(articles),
        "articles": articles,
        "supplementary_count": len(supplementary),
        "supplementary": supplementary,
        "appendices_count": len(appendices),
        "appendices": appendices,
        "excluded_parts": excluded_appendices,
        "part_policy": {
            "include_parts": include_parts,
            "exclude_parts": exclude_parts,
        },
    }


def parse_law_body_record(
    body_record: dict[str, Any],
    *,
    include_parts: list[str] | None = None,
    exclude_parts: list[str] | None = None,
) -> dict[str, Any]:
    law_body = body_record.get("law_body")
    if not isinstance(law_body, dict):
        raise ValueError("body_record must contain dict key 'law_body'")

    law_ref = body_record.get("law_ref")
    if law_ref is not None and not isinstance(law_ref, dict):
        raise ValueError("body_record.law_ref must be a dict if present")

    return parse_law_body(
        law_body,
        law_ref=law_ref,
        include_parts=include_parts,
        exclude_parts=exclude_parts,
    )


def save_parsed_law(
    parsed_law: dict[str, Any],
    save_dir: str | Path,
) -> Path:
    law_name = str(parsed_law.get("law_name") or "unnamed")
    output_path = Path(save_dir) / f"{_safe_filename(law_name)}__parsed_law.json"
    _write_json(output_path, parsed_law)
    return output_path
