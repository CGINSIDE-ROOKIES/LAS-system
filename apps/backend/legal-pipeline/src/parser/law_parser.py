from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

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


Normalizer = Callable[[Any], str | None]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _normalize_text_preserve_structure(value: Any) -> str | None:
    if value in (None, ""):
        return None

    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None

    normalized_lines: list[str] = []
    previous_blank = False

    for raw_line in text.split("\n"):
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

    if not normalized_lines:
        return None

    return "\n".join(normalized_lines)


# 하위 호환용 이름 유지
_normalize_text = _normalize_text_preserve_structure


def _normalize_text_flat(value: Any) -> str | None:
    structured = _normalize_text_preserve_structure(value)
    if structured is None:
        return None
    return re.sub(r"\s+", " ", structured).strip()


def _normalize_title_raw(value: Any) -> str | None:
    return _normalize_text_preserve_structure(value)


def _normalize_title(value: Any) -> str | None:
    return _normalize_text_flat(value)


AuxiliaryContentCategory = Literal["narrative", "table_like", "metadata"]


def _normalize_numeric_token(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    digits = str(value).strip()
    if not digits:
        return None
    stripped = digits.lstrip("0")
    return stripped or "0"


def _extract_article_number_parts(
    article_no: Any,
    *,
    fallback_text: Any = None,
) -> dict[str, str | None]:
    article_no_flat = _normalize_text_flat(article_no)
    fallback_structured = _normalize_text_preserve_structure(fallback_text)
    fallback_flat = _normalize_text_flat(fallback_text)

    article_no_is_plain_numeric = bool(article_no_flat and re.fullmatch(r"\d+", article_no_flat))

    if article_no_is_plain_numeric:
        candidates = [
            fallback_structured,
            fallback_flat,
            article_no_flat,
            _normalize_text_preserve_structure(article_no),
        ]
    else:
        candidates = [
            article_no_flat,
            _normalize_text_preserve_structure(article_no),
            fallback_structured,
            fallback_flat,
        ]

    patterns = (
        re.compile(r"제\s*(\d+)\s*조\s*(?:의\s*(\d+))?"),
        re.compile(r"(?<!\d)(\d+)\s*(?:의|-)?\s*(\d+)?(?!\d)"),
    )

    for candidate in candidates:
        if not candidate:
            continue

        for pattern in patterns:
            match = pattern.search(candidate)
            if not match:
                continue

            main_no = _normalize_numeric_token(match.group(1))
            branch_no = _normalize_numeric_token(match.group(2))
            if main_no is None:
                continue

            display = f"제{main_no}조"
            key = main_no
            if branch_no is not None:
                display = f"{display}의{branch_no}"
                key = f"{key}-{branch_no}"

            return {
                "article_no_display": display,
                "article_no_main": main_no,
                "article_no_branch": branch_no,
                "article_key": key,
            }

    raw_text = _normalize_text_flat(article_no)
    return {
        "article_no_display": raw_text,
        "article_no_main": None,
        "article_no_branch": None,
        "article_key": raw_text,
    }


def _looks_table_like(text: str | None) -> bool:
    if text in (None, ""):
        return False

    raw = str(text)
    if sum(raw.count(ch) for ch in "┌┐└┘├┤┬┴┼│─") >= 3:
        return True

    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return False

    boxed_lines = sum(1 for line in lines if line.count("│") >= 2)
    if boxed_lines >= 2:
        return True

    tabular_lines = sum(1 for line in lines if re.search(r"\S\s{2,}\S", line))
    return tabular_lines >= 3


def _looks_metadata_like(title: str | None, text: str | None) -> bool:
    title_text = _normalize_text_flat(title) or ""
    body_text = _normalize_text_flat(text) or ""
    combined = f"{title_text} {body_text}".strip()

    metadata_title_tokens = (
        "파일링크",
        "PDF파일명",
        "HWP파일명",
        "이미지파일명",
        "시행일자문자열",
        "제목문자열",
        "편집여부",
    )
    metadata_exact_titles = {
        "별표키",
        "별표번호",
        "별표구분",
        "별표가지번호",
        "별표시행일자",
        "부칙키",
        "부칙시행일자",
    }

    if any(token in title_text for token in metadata_title_tokens):
        return True
    if title_text in metadata_exact_titles:
        return True

    if "/LSW/flDownload.do" in combined:
        return True
    if re.fullmatch(r"[^\s]+\.(?:pdf|hwp|hwpx|jpg|jpeg|png|gif|bmp)", body_text, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"https?://\S+", body_text):
        return True

    return False


def _classify_auxiliary_content(
    title: str | None,
    text: str | None,
) -> AuxiliaryContentCategory:
    if _looks_metadata_like(title, text):
        return "metadata"
    if _looks_table_like(text):
        return "table_like"
    return "narrative"


def _dedup_texts(values: Iterable[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = _normalize_text_preserve_structure(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        results.append(text)

    return results


def _walk_strings(
    node: Any,
    *,
    normalizer: Normalizer = _normalize_text_preserve_structure,
) -> Iterable[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value, normalizer=normalizer)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item, normalizer=normalizer)
    elif isinstance(node, str):
        text = normalizer(node)
        if text:
            yield text


def _join_nested_text(
    node: Any,
    *,
    exclude_strings: Iterable[str] = (),
    normalizer: Normalizer = _normalize_text_preserve_structure,
) -> str | None:
    excluded = {
        normalized
        for value in exclude_strings
        if (normalized := normalizer(value))
    }
    texts = [
        text
        for text in _dedup_texts(_walk_strings(node, normalizer=normalizer))
        if text not in excluded
    ]
    if not texts:
        return None
    return "\n".join(texts)


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
        raw_text = _normalize_text_preserve_structure(
            _first_non_empty(unit, *SUBITEM_TEXT_KEYS)
        )
        results.append(
            {
                "mok_code": _first_non_empty(unit, *SUBITEM_CODE_KEYS),
                "subitem_no": _first_non_empty(unit, *SUBITEM_NO_KEYS),
                "subitem_text_raw": raw_text,
                "subitem_text": _normalize_text_flat(raw_text),
            }
        )

    return results


def parse_item_unit(paragraph_unit: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for unit in get_item_units(paragraph_unit):
        raw_text = _normalize_text_preserve_structure(
            _first_non_empty(unit, *ITEM_TEXT_KEYS)
        )
        results.append(
            {
                "ho_code": _first_non_empty(unit, *ITEM_CODE_KEYS),
                "item_no": _first_non_empty(unit, *ITEM_NO_KEYS),
                "item_text_raw": raw_text,
                "item_text": _normalize_text_flat(raw_text),
                "subitems": parse_subitem_unit(unit),
            }
        )

    return results


def parse_paragraph_unit(article_unit: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for unit in get_paragraph_units(article_unit):
        raw_text = _normalize_text_preserve_structure(
            _first_non_empty(unit, *PARAGRAPH_TEXT_KEYS)
        )
        results.append(
            {
                "hang_code": _first_non_empty(unit, *PARAGRAPH_CODE_KEYS),
                "paragraph_no": _first_non_empty(unit, *PARAGRAPH_NO_KEYS),
                "paragraph_text_raw": raw_text,
                "paragraph_text": _normalize_text_flat(raw_text),
                "items": parse_item_unit(unit),
            }
        )

    return results


def parse_article_unit(article_unit: dict[str, Any]) -> dict[str, Any]:
    article_title_raw = _normalize_title_raw(
        _first_non_empty(article_unit, *ARTICLE_TITLE_KEYS)
    )
    article_text_raw = _normalize_text_preserve_structure(
        _first_non_empty(article_unit, *ARTICLE_TEXT_KEYS)
    )
    article_no = _first_non_empty(article_unit, *ARTICLE_NO_KEYS)
    article_no_parts = _extract_article_number_parts(
        article_no,
        fallback_text=article_text_raw,
    )

    return {
        "jo_code": _first_non_empty(article_unit, *ARTICLE_CODE_KEYS),
        "article_no": article_no,
        "article_no_display": article_no_parts["article_no_display"],
        "article_no_main": article_no_parts["article_no_main"],
        "article_no_branch": article_no_parts["article_no_branch"],
        "article_key": article_no_parts["article_key"],
        "article_title_raw": article_title_raw,
        "article_title": _normalize_title(article_title_raw),
        "article_text_raw": article_text_raw,
        "article_text": _normalize_text_flat(article_text_raw),
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
    title_raw = _normalize_title_raw(_first_non_empty(unit, *SUPPLEMENTARY_TITLE_KEYS)) or "부칙"
    text_raw = _normalize_text_preserve_structure(
        _first_non_empty(unit, *SUPPLEMENTARY_TEXT_KEYS)
    )
    if text_raw is None:
        text_raw = _join_nested_text(unit, exclude_strings=[title_raw])

    content_category = _classify_auxiliary_content(title_raw, text_raw)

    return {
        "supplementary_no": _first_non_empty(unit, *SUPPLEMENTARY_NO_KEYS),
        "supplementary_title_raw": title_raw,
        "supplementary_title": _normalize_title(title_raw),
        "supplementary_text_raw": text_raw,
        "supplementary_text": _normalize_text_flat(text_raw),
        "content_category": content_category,
        "is_searchable": content_category == "narrative",
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
        title_raw = _normalize_title_raw(_first_non_empty(candidate, *APPENDIX_TITLE_KEYS))
        if title_raw is None:
            title_raw = _normalize_title_raw(candidate.get("_synthetic_title"))

        if title_raw is None:
            continue

        title = _normalize_title(title_raw) or title_raw

        if not any(token in title for token in ("별표", "별지", "서식")):
            continue

        text_raw = _normalize_text_preserve_structure(
            _first_non_empty(candidate, *APPENDIX_TEXT_KEYS)
        )
        if text_raw is None:
            text_raw = _normalize_text_preserve_structure(candidate.get("_synthetic_text"))
        if text_raw is None:
            text_raw = _join_nested_text(candidate, exclude_strings=[title_raw])
        if text_raw is None:
            continue

        include_hit, exclude_hit = _matches_part_policy(title, include_parts, exclude_parts)
        if not include_hit and not exclude_hit:
            continue

        content_category = _classify_auxiliary_content(title_raw, text_raw)
        record = {
            "appendix_title_raw": title_raw,
            "appendix_title": title,
            "appendix_text_raw": text_raw,
            "appendix_text": _normalize_text_flat(text_raw),
            "content_category": content_category,
            "is_searchable": content_category == "narrative",
            "excluded": exclude_hit,
        }
        dedup_key = (title, text_raw)
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
