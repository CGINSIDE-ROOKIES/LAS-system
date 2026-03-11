from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


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


def _safe_filename(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^\w가-힣.-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "unnamed"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _walk_objects(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_objects(item)


def _first_non_empty(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", []):
            return value
    return None


def _normalize_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    return re.sub(r"\s+", " ", text)


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
        results.append(
            {
                "mok_code": _first_non_empty(unit, *SUBITEM_CODE_KEYS),
                "subitem_no": _first_non_empty(unit, *SUBITEM_NO_KEYS),
                "subitem_text": _normalize_text(
                    _first_non_empty(unit, *SUBITEM_TEXT_KEYS)
                ),
            }
        )

    return results


def parse_item_unit(paragraph_unit: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for unit in get_item_units(paragraph_unit):
        results.append(
            {
                "ho_code": _first_non_empty(unit, *ITEM_CODE_KEYS),
                "item_no": _first_non_empty(unit, *ITEM_NO_KEYS),
                "item_text": _normalize_text(
                    _first_non_empty(unit, *ITEM_TEXT_KEYS)
                ),
                "subitems": parse_subitem_unit(unit),
            }
        )

    return results


def parse_paragraph_unit(article_unit: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for unit in get_paragraph_units(article_unit):
        results.append(
            {
                "hang_code": _first_non_empty(unit, *PARAGRAPH_CODE_KEYS),
                "paragraph_no": _first_non_empty(unit, *PARAGRAPH_NO_KEYS),
                "paragraph_text": _normalize_text(
                    _first_non_empty(unit, *PARAGRAPH_TEXT_KEYS)
                ),
                "items": parse_item_unit(unit),
            }
        )

    return results


def parse_article_unit(article_unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "jo_code": _first_non_empty(
            article_unit,
            "JO",
            "조문번호키",
            "조문번호",
            "jo_code",
        ),
        "article_no": _first_non_empty(article_unit, *ARTICLE_NO_KEYS),
        "article_title": _normalize_text(
            _first_non_empty(article_unit, *ARTICLE_TITLE_KEYS)
        ),
        "article_text": _normalize_text(
            _first_non_empty(article_unit, *ARTICLE_TEXT_KEYS)
        ),
        "paragraphs": parse_paragraph_unit(article_unit),
    }


def parse_law_body(payload: dict[str, Any], law_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    law_root = get_law_root(payload)
    article_units = get_article_units(law_root)

    articles = [parse_article_unit(unit) for unit in article_units]

    return {
        "law_name": (law_ref or {}).get("law_name")
        or _first_non_empty(law_root, "법령명한글", "법령명"),
        "law_id": (law_ref or {}).get("law_id")
        or _first_non_empty(law_root, "법령ID", "law_id"),
        "mst": (law_ref or {}).get("mst")
        or _first_non_empty(law_root, "법령일련번호", "mst"),
        "ef_yd": (law_ref or {}).get("ef_yd")
        or _first_non_empty(law_root, "시행일자", "ef_yd"),
        "articles_count": len(articles),
        "articles": articles,
    }


def parse_law_body_record(body_record: dict[str, Any]) -> dict[str, Any]:
    law_body = body_record.get("law_body")
    if not isinstance(law_body, dict):
        raise ValueError("body_record must contain dict key 'law_body'")

    law_ref = body_record.get("law_ref")
    if law_ref is not None and not isinstance(law_ref, dict):
        raise ValueError("body_record.law_ref must be a dict if present")

    return parse_law_body(law_body, law_ref=law_ref)


def save_parsed_law(
    parsed_law: dict[str, Any],
    save_dir: str | Path,
) -> Path:
    law_name = str(parsed_law.get("law_name") or "unnamed")
    output_path = Path(save_dir) / f"{_safe_filename(law_name)}__parsed_law.json"
    _write_json(output_path, parsed_law)
    return output_path