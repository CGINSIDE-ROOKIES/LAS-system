from __future__ import annotations

import ast
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Literal

from src.collector.legal_doc_collector import (
    DETAIL_LINK_KEYS_BY_TARGET,
    DOC_KIND_KEYS,
    DOC_TYPE_LABELS,
    ID_KEYS_BY_TARGET,
    NUMBER_KEYS_BY_TARGET,
    TARGET_CONFIGS,
    TITLE_KEYS_BY_TARGET,
    build_doc_ref,
    extract_list_items,
)
from src.common.law_meta import (
    build_law_uid,
    build_record_id,
    build_strict_law_uid,
    normalize_classified_level,
    normalize_kind_name,
)
from src.common.io_utils import _iter_jsonl, _read_json, _write_json, write_jsonl
from src.common.payload_utils import _first_non_empty, _walk_objects
from src.common.url_utils import sanitize_detail_link
from src.export.qdrant_point_id import build_qdrant_point_id, duplicate_canonical_ids

TextVariant = Literal["best", "raw", "normalized"]


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


def _stem_to_name(stem: str) -> str:
    return stem.replace("_", " ").strip()


def _walk_strings(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)
    elif isinstance(node, str):
        text = _normalize_space(node)
        if text:
            yield text


def _find_first_recursive(node: Any, keys: tuple[str, ...]) -> Any:
    for obj in _walk_objects(node):
        if not isinstance(obj, dict):
            continue
        value = _first_non_empty(obj, *keys)
        if value not in (None, "", []):
            return value
    return None


def _dedup_texts(texts: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for text in texts:
        normalized = _normalize_space(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)

    return results


_IMG_TAG_RE = re.compile(r"<img[^>]*/?>", re.IGNORECASE)


def _normalize_law_text(text: str, *, preserve_structure: bool) -> str:
    text = _IMG_TAG_RE.sub("", text).strip()
    return _normalize_structure(text) if preserve_structure else _normalize_space(text)


def _now_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _truncate_text(text: str, limit: int = 320) -> str:
    normalized = _normalize_space(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 1)].rstrip() + "…"


def _build_text_fields(
    *,
    text: str,
    title: str | None = None,
    law_name: str | None = None,
    article_no_display: str | None = None,
    doc_number: str | None = None,
    extra_lines: list[str] | None = None,
) -> dict[str, str]:
    extra_lines = extra_lines or []
    search_parts = [law_name, article_no_display, title, doc_number]
    search_parts.extend(extra_lines)
    search_parts.append(text)
    search_text = "\n".join(str(item).strip() for item in search_parts if str(item or "").strip()).strip()
    display_prefix = "\n".join(
        str(item).strip()
        for item in (law_name, article_no_display, title, doc_number)
        if str(item or "").strip()
    ).strip()
    display_body = _truncate_text(text)
    display_text = "\n".join(part for part in (display_prefix, display_body) if part).strip()
    return {
        "text": text,
        "search_text": search_text or text,
        "display_text": display_text or _truncate_text(text),
    }


def _article_display_no(article: dict[str, Any]) -> str:
    return str(
        article.get("article_no_display")
        or article.get("article_no")
        or article.get("jo_code")
        or ""
    ).strip()


def _article_record_key(article: dict[str, Any]) -> str:
    return str(
        article.get("article_key")
        or article.get("article_no_display")
        or article.get("article_no")
        or article.get("jo_code")
        or ""
    ).strip()


def _aux_part_content_category(part: dict[str, Any]) -> str:
    return str(part.get("content_category") or "narrative").strip() or "narrative"


def _is_searchable_aux_part(part: dict[str, Any]) -> bool:
    if "is_searchable" in part:
        return bool(part.get("is_searchable"))
    return _aux_part_content_category(part) == "narrative"


def _candidate_field_keys(
    base_field: str,
    *,
    text_variant: TextVariant,
    preserve_structure: bool,
) -> tuple[str, ...]:
    raw_key = f"{base_field}_raw"
    normalized_key = base_field

    if text_variant == "raw":
        return (raw_key, normalized_key)
    if text_variant == "normalized":
        return (normalized_key, raw_key)

    if preserve_structure:
        return (raw_key, normalized_key)
    return (normalized_key, raw_key)


def _select_law_text(
    node: dict[str, Any],
    base_field: str,
    *,
    text_variant: TextVariant,
    preserve_structure: bool,
) -> str:
    for key in _candidate_field_keys(
        base_field,
        text_variant=text_variant,
        preserve_structure=preserve_structure,
    ):
        value = node.get(key)
        if value in (None, ""):
            continue
        return _normalize_law_text(str(value), preserve_structure=preserve_structure)
    return ""


def _render_prefixed_text(prefix: str, text: str) -> str:
    prefix = prefix.strip()
    text = text.strip()

    if not prefix:
        return text
    if not text:
        return prefix

    lines = text.splitlines()
    if len(lines) == 1:
        return f"{prefix} {lines[0]}".strip()

    indent = " " * (len(prefix) + 1)
    rendered = [f"{prefix} {lines[0]}".rstrip()]
    rendered.extend(f"{indent}{line}" if line else "" for line in lines[1:])
    return "\n".join(rendered).strip()


def _split_long_line(line: str, max_chars: int) -> list[str]:
    line = line.strip()
    if not line:
        return []
    if len(line) <= max_chars:
        return [line]

    parts: list[str] = []
    remaining = line

    while len(remaining) > max_chars:
        split_candidates = [
            remaining.rfind(" ", 0, max_chars),
            remaining.rfind(",", 0, max_chars),
            remaining.rfind("·", 0, max_chars),
        ]
        split = max(split_candidates)
        if split <= max_chars // 2:
            split = max_chars

        parts.append(remaining[:split].rstrip())
        remaining = remaining[split:].lstrip()

    if remaining:
        parts.append(remaining)

    return parts


def _split_structured_segment(segment: str, max_chars: int) -> list[str]:
    segment = _normalize_structure(segment)
    if not segment:
        return []
    if len(segment) <= max_chars:
        return [segment]

    results: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for raw_line in segment.splitlines():
        line_parts = _split_long_line(raw_line, max_chars) or [""]

        for line in line_parts:
            separator_len = 1 if current_lines else 0
            next_len = current_len + separator_len + len(line)
            if current_lines and next_len > max_chars:
                results.append("\n".join(current_lines).strip())
                current_lines = []
                current_len = 0
                separator_len = 0

            current_lines.append(line)
            current_len += separator_len + len(line)

    if current_lines:
        results.append("\n".join(current_lines).strip())

    return [result for result in results if result]


def _tail_overlap_by_lines(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""

    selected: list[str] = []
    current_len = 0

    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue

        separator_len = 1 if selected else 0
        next_len = current_len + separator_len + len(stripped)
        if selected and next_len > max_chars:
            break

        selected.append(stripped)
        current_len = next_len
        if current_len >= max_chars:
            break

    return "\n".join(reversed(selected)).strip()


def _chunk_text(
    text: str,
    max_chars: int = 1200,
    overlap: int = 150,
    *,
    preserve_structure: bool = False,
) -> list[str]:
    text = _normalize_law_text(text, preserve_structure=preserve_structure)
    if not text:
        return []

    if len(text) <= max_chars:
        return [text]

    if not preserve_structure:
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

    segments: list[str] = []
    for block in re.split(r"\n{2,}", text):
        block = block.strip()
        if not block:
            continue
        segments.extend(_split_structured_segment(block, max_chars))

    if not segments:
        return []

    chunks: list[str] = []
    current = ""

    for segment in segments:
        candidate = segment if not current else f"{current}\n\n{segment}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            overlap_seed = _tail_overlap_by_lines(current, overlap)
        else:
            overlap_seed = ""

        if overlap_seed and len(f"{overlap_seed}\n\n{segment}") <= max_chars:
            current = f"{overlap_seed}\n\n{segment}"
        else:
            current = segment

    if current:
        chunks.append(current)

    return chunks


def _format_subitems(
    subitems: list[dict[str, Any]],
    *,
    text_variant: TextVariant,
    preserve_structure: bool,
) -> list[str]:
    lines: list[str] = []

    for subitem in subitems:
        if not isinstance(subitem, dict):
            continue

        prefix = str(subitem.get("subitem_no") or subitem.get("mok_code") or "").strip()
        text = _select_law_text(
            subitem,
            "subitem_text",
            text_variant=text_variant,
            preserve_structure=preserve_structure,
        )

        if text:
            lines.append(_render_prefixed_text(prefix, text))
        elif prefix:
            lines.append(prefix)

    return lines


def _format_items(
    items: list[dict[str, Any]],
    *,
    text_variant: TextVariant,
    preserve_structure: bool,
) -> list[str]:
    lines: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        prefix = str(item.get("item_no") or item.get("ho_code") or "").strip()
        text = _select_law_text(
            item,
            "item_text",
            text_variant=text_variant,
            preserve_structure=preserve_structure,
        )

        if text:
            lines.append(_render_prefixed_text(prefix, text))
        elif prefix:
            lines.append(prefix)

        lines.extend(
            _format_subitems(
                item.get("subitems", []),
                text_variant=text_variant,
                preserve_structure=preserve_structure,
            )
        )

    return lines


def _format_paragraphs(
    paragraphs: list[dict[str, Any]],
    *,
    text_variant: TextVariant,
    preserve_structure: bool,
) -> list[str]:
    lines: list[str] = []

    for paragraph in paragraphs:
        if not isinstance(paragraph, dict):
            continue

        prefix = str(paragraph.get("paragraph_no") or paragraph.get("hang_code") or "").strip()
        text = _select_law_text(
            paragraph,
            "paragraph_text",
            text_variant=text_variant,
            preserve_structure=preserve_structure,
        )

        if text:
            lines.append(_render_prefixed_text(prefix, text))
        elif prefix:
            lines.append(prefix)

        lines.extend(
            _format_items(
                paragraph.get("items", []),
                text_variant=text_variant,
                preserve_structure=preserve_structure,
            )
        )

    return lines


def _build_law_article_text(
    parsed_law: dict[str, Any],
    article: dict[str, Any],
    *,
    text_variant: TextVariant,
    preserve_structure: bool,
) -> str:
    law_name = str(parsed_law.get("law_name") or "").strip()
    article_no = _article_display_no(article)
    article_title = _select_law_text(
        article,
        "article_title",
        text_variant=text_variant,
        preserve_structure=preserve_structure,
    )
    article_text = _select_law_text(
        article,
        "article_text",
        text_variant=text_variant,
        preserve_structure=preserve_structure,
    )

    lines = []
    if law_name:
        lines.append(f"법령명: {law_name}")
    if article_no:
        lines.append(f"조문번호: {article_no}")
    if article_title:
        lines.append(_render_prefixed_text("조문제목:", article_title))
    if article_text:
        lines.append(article_text)

    lines.extend(
        _format_paragraphs(
            article.get("paragraphs", []),
            text_variant=text_variant,
            preserve_structure=preserve_structure,
        )
    )

    return "\n".join(line for line in lines if line).strip()


def _parse_raw_list_text(text: str) -> str:
    """normalized JSON에 '[[\\'...\\']]' 형태로 baked-in된 부칙 텍스트를 정상 텍스트로 변환."""
    stripped = text.strip()
    if not (stripped.startswith("[[") or stripped.startswith("['")):
        return text
    try:
        parsed = ast.literal_eval(stripped)
        if isinstance(parsed, list):
            lines = []
            for item in parsed:
                if isinstance(item, list):
                    lines.extend(str(x).strip() for x in item if x)
                elif item:
                    lines.append(str(item).strip())
            return "\n".join(lines)
    except (ValueError, SyntaxError):
        pass
    return text


def _build_supplementary_text(
    parsed_law: dict[str, Any],
    supplementary: dict[str, Any],
    *,
    text_variant: TextVariant,
    preserve_structure: bool,
) -> str:
    law_name = str(parsed_law.get("law_name") or "").strip()
    title = _select_law_text(
        supplementary,
        "supplementary_title",
        text_variant=text_variant,
        preserve_structure=preserve_structure,
    ) or "부칙"
    number = str(supplementary.get("supplementary_no") or "").strip()
    text = _select_law_text(
        supplementary,
        "supplementary_text",
        text_variant=text_variant,
        preserve_structure=preserve_structure,
    )

    lines = []
    if law_name:
        lines.append(f"법령명: {law_name}")
    lines.append("구성요소: 부칙")
    if title:
        lines.append(_render_prefixed_text("부칙제목:", title))
    if number:
        lines.append(f"부칙번호: {number}")
    if text:
        lines.append(_parse_raw_list_text(text))

    return "\n".join(line for line in lines if line).strip()


def _build_appendix_text(
    parsed_law: dict[str, Any],
    appendix: dict[str, Any],
    *,
    text_variant: TextVariant,
    preserve_structure: bool,
) -> str:
    law_name = str(parsed_law.get("law_name") or "").strip()
    title = _select_law_text(
        appendix,
        "appendix_title",
        text_variant=text_variant,
        preserve_structure=preserve_structure,
    ) or "별표"
    text = _select_law_text(
        appendix,
        "appendix_text",
        text_variant=text_variant,
        preserve_structure=preserve_structure,
    )

    lines = []
    if law_name:
        lines.append(f"법령명: {law_name}")
    lines.append("구성요소: 별표")
    if title:
        lines.append(_render_prefixed_text("별표제목:", title))
    if text:
        lines.append(text)

    return "\n".join(line for line in lines if line).strip()


def _normalize_law_meta(parsed_law: dict[str, Any]) -> tuple[str | None, str]:
    kind_name = normalize_kind_name(parsed_law.get("kind_name"))
    classified_level = normalize_classified_level(
        kind_name,
        parsed_law.get("classified_level"),
    )
    return kind_name, classified_level


_DELETED_ARTICLE_RE = re.compile(r"제\d+(?:조의\d+|조)\s+삭제", re.UNICODE)


def _is_header_only_supplementary(text: str) -> bool:
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    content = [
        l for l in lines
        if not l.startswith("법령명:")
        and l not in {"구성요소: 부칙", "부칙제목: 부칙"}
        and not l.startswith("부칙제목:")
    ]
    return len(content) == 0


def _ensure_unique_record_id(
    record_id: str,
    seen_ids: dict[str, int],
) -> str:
    count = seen_ids.get(record_id, 0)
    seen_ids[record_id] = count + 1
    if count == 0:
        return record_id
    return f"{record_id}::dup{count}"


def build_law_records(
    normalized_base_dir: str | Path = "data/normalized/01_current_law",
    max_chars: int = 1200,
    overlap: int = 150,
    *,
    text_variant: TextVariant = "best",
    preserve_structure: bool = True,
    include_non_searchable_law_parts: bool = False,
    include_appendix_as_law_rows: bool = False,
) -> list[dict[str, Any]]:
    base_dir = Path(normalized_base_dir)
    records: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}

    for path in sorted(base_dir.rglob("*__parsed_law.json")):
        parsed_law = _read_json(path)

        law_name = str(parsed_law.get("law_name") or "").strip()
        root_law_name = path.parent.name.replace("_", " ").strip() or law_name
        law_id = parsed_law.get("law_id")
        mst = parsed_law.get("mst")
        ef_yd = parsed_law.get("ef_yd")
        kind_name, classified_level = _normalize_law_meta(parsed_law)
        scope_source = parsed_law.get("scope_source")
        law_uid = build_law_uid(law_id, mst, law_name)
        root_law_uid = build_strict_law_uid(law_id, mst)

        articles = parsed_law.get("articles", [])
        if isinstance(articles, list):
            for article_index, article in enumerate(articles):
                if not isinstance(article, dict):
                    continue

                article_no = article.get("article_no")
                article_no_display = article.get("article_no_display") or article_no
                article_no_main = article.get("article_no_main")
                article_no_branch = article.get("article_no_branch")
                article_key = _article_record_key(article)
                jo_code = article.get("jo_code")
                article_text = _build_law_article_text(
                    parsed_law,
                    article,
                    text_variant=text_variant,
                    preserve_structure=preserve_structure,
                )
                if _DELETED_ARTICLE_RE.search(article_text) and len(article_text) < 150:
                    continue
                chunks = _chunk_text(
                    article_text,
                    max_chars=max_chars,
                    overlap=overlap,
                    preserve_structure=preserve_structure,
                )

                for chunk_index, chunk in enumerate(chunks):
                    section_uid = article_key or f"article-{article_index}"
                    record_id = build_record_id(
                        prefix="law",
                        law_id=law_id,
                        mst=mst,
                        law_name=law_name,
                        section_type="article",
                        section_uid=section_uid,
                        chunk_index=chunk_index,
                    )
                    record_id = _ensure_unique_record_id(record_id, seen_ids)
                    text_fields = _build_text_fields(
                        text=chunk,
                        law_name=law_name,
                        article_no_display=str(article_no_display or ""),
                        extra_lines=[str(kind_name or ""), str(classified_level or "")],
                    )

                    records.append(
                        {
                            "id": record_id,
                            "canonical_id": record_id,
                            "doc_type": "law",
                            "section_type": "article",
                            "source_group": "01_current_law",
                            "law_name": law_name,
                            "law_id": law_id,
                            "mst": mst,
                            "ef_yd": ef_yd,
                            "kind_name": kind_name,
                            "classified_level": classified_level,
                            "law_level": classified_level,
                            "law_uid": law_uid,
                            "root_law_name": root_law_name,
                            "root_law_uid": root_law_uid,
                            "scope_source": scope_source,
                            "article_no": article_no,
                            "article_no_display": article_no_display,
                            "article_no_main": article_no_main,
                            "article_no_branch": article_no_branch,
                            "article_key": article_key,
                            "jo_code": jo_code,
                            "chunk_index": chunk_index,
                            "text_variant": text_variant,
                            "structure_preserved": preserve_structure,
                            "source_file_path": str(path),
                            **text_fields,
                        }
                    )

        supplementary_items = parsed_law.get("supplementary", [])
        if isinstance(supplementary_items, list):
            for item_index, supplementary in enumerate(supplementary_items):
                if not isinstance(supplementary, dict):
                    continue
                if not include_non_searchable_law_parts and not _is_searchable_aux_part(supplementary):
                    continue

                text = _build_supplementary_text(
                    parsed_law,
                    supplementary,
                    text_variant=text_variant,
                    preserve_structure=preserve_structure,
                )
                if _is_header_only_supplementary(text):
                    continue
                chunks = _chunk_text(
                    text,
                    max_chars=max_chars,
                    overlap=overlap,
                    preserve_structure=preserve_structure,
                )

                for chunk_index, chunk in enumerate(chunks):
                    section_uid = supplementary.get("supplementary_no") or f"supplementary-{item_index}"
                    record_id = build_record_id(
                        prefix="law",
                        law_id=law_id,
                        mst=mst,
                        law_name=law_name,
                        section_type="supplementary",
                        section_uid=section_uid,
                        chunk_index=chunk_index,
                    )
                    record_id = _ensure_unique_record_id(record_id, seen_ids)
                    text_fields = _build_text_fields(
                        text=chunk,
                        law_name=law_name,
                        title=str(supplementary.get("supplementary_title") or ""),
                        extra_lines=[str(kind_name or ""), str(classified_level or "")],
                    )

                    records.append(
                        {
                            "id": record_id,
                            "canonical_id": record_id,
                            "doc_type": "law",
                            "section_type": "supplementary",
                            "source_group": "01_current_law",
                            "law_name": law_name,
                            "law_id": law_id,
                            "mst": mst,
                            "ef_yd": ef_yd,
                            "kind_name": kind_name,
                            "classified_level": classified_level,
                            "law_level": classified_level,
                            "law_uid": law_uid,
                            "root_law_name": root_law_name,
                            "root_law_uid": root_law_uid,
                            "scope_source": scope_source,
                            "supplementary_no": supplementary.get("supplementary_no"),
                            "supplementary_title": supplementary.get("supplementary_title"),
                            "content_category": _aux_part_content_category(supplementary),
                            "is_searchable": _is_searchable_aux_part(supplementary),
                            "chunk_index": chunk_index,
                            "text_variant": text_variant,
                            "structure_preserved": preserve_structure,
                            "source_file_path": str(path),
                            **text_fields,
                        }
                    )

        appendices = parsed_law.get("appendices", [])
        if include_appendix_as_law_rows and isinstance(appendices, list):
            for item_index, appendix in enumerate(appendices):
                if not isinstance(appendix, dict):
                    continue
                if not include_non_searchable_law_parts and not _is_searchable_aux_part(appendix):
                    continue

                text = _build_appendix_text(
                    parsed_law,
                    appendix,
                    text_variant=text_variant,
                    preserve_structure=preserve_structure,
                )
                chunks = _chunk_text(
                    text,
                    max_chars=max_chars,
                    overlap=overlap,
                    preserve_structure=preserve_structure,
                )

                for chunk_index, chunk in enumerate(chunks):
                    section_uid = appendix.get("appendix_title") or f"appendix-{item_index}"
                    record_id = build_record_id(
                        prefix="law",
                        law_id=law_id,
                        mst=mst,
                        law_name=law_name,
                        section_type="appendix",
                        section_uid=section_uid,
                        chunk_index=chunk_index,
                    )
                    record_id = _ensure_unique_record_id(record_id, seen_ids)
                    text_fields = _build_text_fields(
                        text=chunk,
                        law_name=law_name,
                        title=str(appendix.get("appendix_title") or ""),
                        extra_lines=[str(kind_name or ""), str(classified_level or "")],
                    )

                    records.append(
                        {
                            "id": record_id,
                            "canonical_id": record_id,
                            "doc_type": "law",
                            "section_type": "appendix",
                            "source_group": "01_current_law",
                            "law_name": law_name,
                            "law_id": law_id,
                            "mst": mst,
                            "ef_yd": ef_yd,
                            "kind_name": kind_name,
                            "classified_level": classified_level,
                            "law_level": classified_level,
                            "law_uid": law_uid,
                            "root_law_name": root_law_name,
                            "root_law_uid": root_law_uid,
                            "scope_source": scope_source,
                            "appendix_title": appendix.get("appendix_title"),
                            "content_category": _aux_part_content_category(appendix),
                            "is_searchable": _is_searchable_aux_part(appendix),
                            "chunk_index": chunk_index,
                            "text_variant": text_variant,
                            "structure_preserved": preserve_structure,
                            "source_file_path": str(path),
                            **text_fields,
                        }
                    )

    return records


def _extract_doc_meta_from_payload(target: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc_id = _find_first_recursive(payload, ID_KEYS_BY_TARGET[target])
    title = _find_first_recursive(payload, TITLE_KEYS_BY_TARGET[target])
    doc_number = _find_first_recursive(payload, NUMBER_KEYS_BY_TARGET[target])
    detail_link = _find_first_recursive(payload, DETAIL_LINK_KEYS_BY_TARGET[target])
    doc_kind = _find_first_recursive(payload, DOC_KIND_KEYS)

    return {
        "doc_id": str(doc_id) if doc_id is not None else None,
        "title": str(title) if title is not None else None,
        "doc_number": str(doc_number) if doc_number is not None else None,
        "detail_link": sanitize_detail_link(str(detail_link)) if detail_link is not None else None,
        "doc_kind": str(doc_kind) if doc_kind is not None else None,
    }


def _build_related_doc_records_from_text(
    *,
    root_law_name: str,
    source_law_name: str,
    target: str,
    doc_meta: dict[str, Any],
    text: str,
    source_file_path: str,
    max_chars: int,
    overlap: int,
) -> list[dict[str, Any]]:
    chunks = _chunk_text(
        text,
        max_chars=max_chars,
        overlap=overlap,
        preserve_structure=False,
    )
    records: list[dict[str, Any]] = []

    for chunk_index, chunk in enumerate(chunks):
        prefix = [
            f"루트 법령: {root_law_name}",
            f"관련 법령: {source_law_name}",
            f"문서 유형: {DOC_TYPE_LABELS[target]}",
        ]
        if doc_meta.get("title"):
            prefix.append(f"문서 제목: {doc_meta['title']}")
        if doc_meta.get("doc_number"):
            prefix.append(f"문서 번호: {doc_meta['doc_number']}")
        if doc_meta.get("doc_kind"):
            prefix.append(f"문서 구분: {doc_meta['doc_kind']}")

        full_text = "\n".join(prefix + [chunk]).strip()

        record_id = "::".join(
            [
                target,
                str(doc_meta.get("doc_id") or doc_meta.get("title") or "unknown"),
                str(chunk_index),
            ]
        )

        text_fields = _build_text_fields(
            text=full_text,
            title=str(doc_meta.get("title") or ""),
            law_name=source_law_name,
            doc_number=str(doc_meta.get("doc_number") or ""),
            extra_lines=[DOC_TYPE_LABELS[target], root_law_name],
        )

        records.append(
            {
                "id": record_id,
                "canonical_id": record_id,
                "doc_type": target,
                "doc_type_label": DOC_TYPE_LABELS[target],
                "source_group": "02_related_legal_docs",
                "root_law_name": root_law_name,
                "root_law_uid": build_strict_law_uid(None, None),
                "related_law_name": source_law_name,
                "doc_id": doc_meta.get("doc_id"),
                "title": doc_meta.get("title"),
                "doc_number": doc_meta.get("doc_number"),
                "detail_link": doc_meta.get("detail_link"),
                "doc_kind": doc_meta.get("doc_kind"),
                "chunk_index": chunk_index,
                "source_file_path": source_file_path,
                **text_fields,
            }
        )

    return records


def _build_related_doc_records_legacy(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    max_chars: int = 1200,
    overlap: int = 150,
) -> list[dict[str, Any]]:
    base_dir = Path(raw_related_base_dir)
    records: list[dict[str, Any]] = []

    detail_supported_targets = {
        target
        for target, config in TARGET_CONFIGS.items()
        if config["detail_endpoint"] is not None
    }
    list_only_targets = {
        target
        for target, config in TARGET_CONFIGS.items()
        if config["detail_endpoint"] is None
    }

    for path in sorted(base_dir.rglob("*__detail.json")):
        if len(path.parts) < 5:
            continue

        source_law_name = _stem_to_name(path.parent.name)
        target = path.parent.parent.name
        root_law_name = _stem_to_name(path.parent.parent.parent.name)

        if target not in detail_supported_targets:
            continue

        payload = _read_json(path)
        texts = _dedup_texts(list(_walk_strings(payload)))
        joined_text = "\n".join(texts)
        if not joined_text:
            continue

        doc_meta = _extract_doc_meta_from_payload(target, payload)

        records.extend(
            _build_related_doc_records_from_text(
                root_law_name=root_law_name,
                source_law_name=source_law_name,
                target=target,
                doc_meta=doc_meta,
                text=joined_text,
                source_file_path=str(path),
                max_chars=max_chars,
                overlap=overlap,
            )
        )

    for path in sorted(base_dir.rglob("*__list.json")):
        if len(path.parts) < 5:
            continue

        source_law_name = _stem_to_name(path.parent.name)
        target = path.parent.parent.name
        root_law_name = _stem_to_name(path.parent.parent.parent.name)

        if target not in list_only_targets:
            continue

        payload = _read_json(path)
        items = extract_list_items(payload, target)

        for item in items:
            ref = build_doc_ref(target, source_law_name, item)
            texts = _dedup_texts(list(_walk_strings(item)))
            joined_text = "\n".join(texts)
            if not joined_text:
                continue

            doc_meta = {
                "doc_id": ref.get("doc_id"),
                "title": ref.get("title"),
                "doc_number": ref.get("doc_number"),
                "detail_link": ref.get("detail_link"),
                "doc_kind": ref.get("doc_kind"),
            }

            records.extend(
                _build_related_doc_records_from_text(
                    root_law_name=root_law_name,
                    source_law_name=source_law_name,
                    target=target,
                    doc_meta=doc_meta,
                    text=joined_text,
                    source_file_path=str(path),
                    max_chars=max_chars,
                    overlap=overlap,
                )
            )

    return records


def _build_relation_records_legacy(
    expanded_base_dir: str | Path = "data/expanded/03_expanded_related_docs",
) -> list[dict[str, Any]]:
    base_dir = Path(expanded_base_dir)
    records: list[dict[str, Any]] = []

    for path in sorted(base_dir.rglob("*__expanded.json")):
        payload = _read_json(path)

        text = str(payload.get("embedding_text") or "").strip()
        if not text:
            continue

        record_id = "::".join(
            [
                "relation",
                str(payload.get("target") or "unknown"),
                str(payload.get("doc_id") or payload.get("title") or path.stem),
            ]
        )

        records.append(
            {
                "id": record_id,
                "canonical_id": record_id,
                "text": text,
                "search_text": text,
                "display_text": _truncate_text(text),
                "doc_type": "relation",
                "source_group": "03_expanded_related_docs",
                "target": payload.get("target"),
                "doc_type_label": payload.get("doc_type_label"),
                "root_law_name": payload.get("root_law_name"),
                "root_law_uid": build_strict_law_uid(None, None),
                "source_law_name": payload.get("source_law_name"),
                "source_law_uid": build_law_uid(None, None, payload.get("source_law_name")),
                "law_name": payload.get("source_law_name"),
                "law_uid": build_law_uid(None, None, payload.get("source_law_name")),
                "relation_model": "law_to_case",
                "relation_type": "search_hit",
                "related_law_names": payload.get("related_law_names", []),
                "relation_types": payload.get("relation_types", []),
                "doc_id": payload.get("doc_id"),
                "title": payload.get("title"),
                "doc_number": payload.get("doc_number"),
                "source_file_path": str(path),
            }
        )

    return records


def build_related_doc_records(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    max_chars: int = 1200,
    overlap: int = 150,
    verified_law_case_relations: list[dict] | None = None,
) -> list[dict[str, Any]]:
    from src.export.legal_case_dataset_builder import build_legal_case_records

    records = build_legal_case_records(
        raw_related_base_dir=raw_related_base_dir,
        max_chars=max_chars,
        overlap=overlap,
        verified_law_case_relations=verified_law_case_relations,
    )
    if records:
        return records

    return _build_related_doc_records_legacy(
        raw_related_base_dir=raw_related_base_dir,
        max_chars=max_chars,
        overlap=overlap,
    )



def build_relation_records(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    expanded_base_dir: str | Path = "data/expanded/03_expanded_related_docs",
    normalized_base_dir: str | Path | None = None,
    include_law_to_law_relations: bool = True,
    include_case_to_case_relations: bool = True,
) -> list[dict[str, Any]]:
    from src.export.legal_relation_builder import build_legal_relation_records
    from src.export.law_to_law_relation_builder import build_law_to_law_relation_records

    law_case_records = build_legal_relation_records(
        expanded_base_dir=expanded_base_dir,
        raw_related_base_dir=raw_related_base_dir,
    )
    records = list(law_case_records)
    if not records:
        records = _build_relation_records_legacy(
            expanded_base_dir=expanded_base_dir,
        )

    if include_law_to_law_relations and normalized_base_dir is not None:
        records.extend(build_law_to_law_relation_records(normalized_base_dir=normalized_base_dir))

    if include_case_to_case_relations:
        from src.export.legal_case_relation_builder import build_case_to_case_relation_records
        records.extend(build_case_to_case_relation_records(
            raw_related_base_dir=raw_related_base_dir,
            skip_source_targets={"decc"},
        ))

    records.sort(key=lambda row: str(row.get("id") or ""))
    return records


def build_case_reference_audit_records(
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    *,
    include_body_regex: bool = True,
) -> list[dict[str, Any]]:
    from src.export.legal_case_relation_builder import build_case_reference_audit_records as _build_case_reference_audit_records

    return _build_case_reference_audit_records(
        raw_related_base_dir=raw_related_base_dir,
        include_body_regex=include_body_regex,
    )


def build_and_write_datasets(
    normalized_base_dir: str | Path = "data/normalized/01_current_law",
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    expanded_base_dir: str | Path = "data/expanded/03_expanded_related_docs",
    output_dir: str | Path = "data/dataset",
    max_chars: int = 1200,
    overlap: int = 150,
    *,
    text_variant: TextVariant = "best",
    preserve_structure: bool = True,
    include_non_searchable_law_parts: bool = False,
    normalized_appendix_base_dir: str | Path | None = None,
    normalized_appendix_asset_base_dir: str | Path | None = None,
    merge_appendices_into_law_article: bool = True,
    include_appendix_bundle_text_in_payload: bool = True,
    write_legacy_appendix_datasets: bool = True,
    include_law_to_law_relations: bool = True,
    audit_include_body_regex: bool = True,
) -> dict[str, Any]:
    output_dir = Path(output_dir)

    law_records = build_law_records(
        normalized_base_dir=normalized_base_dir,
        max_chars=max_chars,
        overlap=overlap,
        text_variant=text_variant,
        preserve_structure=preserve_structure,
        include_non_searchable_law_parts=include_non_searchable_law_parts,
        include_appendix_as_law_rows=False,
    )
    # relation_records를 먼저 빌드하여 검증된 law_to_case를 legal_case 메타/텍스트에 반영
    relation_records = build_relation_records(
        raw_related_base_dir=raw_related_base_dir,
        expanded_base_dir=expanded_base_dir,
        normalized_base_dir=normalized_base_dir,
        include_law_to_law_relations=include_law_to_law_relations,
    )
    law_case_rows = [r for r in relation_records if r.get("relation_model") == "law_to_case"]
    related_records = build_related_doc_records(
        raw_related_base_dir=raw_related_base_dir,
        max_chars=max_chars,
        overlap=overlap,
        verified_law_case_relations=law_case_rows,
    )
    case_reference_audit_records = build_case_reference_audit_records(
        raw_related_base_dir=raw_related_base_dir,
        include_body_regex=audit_include_body_regex,
    )

    appendix_manifest: dict[str, Any] | None = None
    if normalized_appendix_base_dir is not None and write_legacy_appendix_datasets:
        from src.export.appendix_dataset_builder import build_and_write_appendix_datasets

        appendix_manifest = build_and_write_appendix_datasets(
            normalized_appendix_base_dir=normalized_appendix_base_dir,
            output_dir=output_dir,
            max_chars=max_chars,
            overlap=overlap,
            normalized_appendix_asset_base_dir=normalized_appendix_asset_base_dir,
        )

    article_appendix_manifest: dict[str, Any] | None = None
    if merge_appendices_into_law_article and normalized_appendix_base_dir is not None:
        from src.export.article_appendix_linker import (
            augment_law_records_with_appendices,
            build_article_appendix_links,
            write_article_appendix_outputs,
        )

        article_appendix_result = build_article_appendix_links(
            normalized_base_dir=normalized_base_dir,
            normalized_appendix_base_dir=normalized_appendix_base_dir,
            normalized_appendix_asset_base_dir=normalized_appendix_asset_base_dir,
        )
        law_records = augment_law_records_with_appendices(
            law_records,
            article_links=article_appendix_result["article_links"],
            include_bundle_text_in_payload=include_appendix_bundle_text_in_payload,
        )
        write_article_appendix_outputs(
            output_dir,
            link_records=article_appendix_result["link_records"],
            appendix_bundle_records=article_appendix_result["appendix_bundle_records"],
            unresolved_appendix_records=article_appendix_result["unresolved_appendix_records"],
            manifest=article_appendix_result["manifest"],
        )
        article_appendix_manifest = article_appendix_result["manifest"]

    legal_corpus_records = law_records + related_records

    write_jsonl(legal_corpus_records, output_dir / "legal_corpus.jsonl")
    write_jsonl(relation_records, output_dir / "legal_relations.jsonl")
    write_jsonl(case_reference_audit_records, output_dir / "case_reference_audit.jsonl")

    case_reference_audit_manifest = {
        "audit_record_count": len(case_reference_audit_records),
        "resolved_count": sum(1 for row in case_reference_audit_records if row.get("resolution_status") == "resolved"),
        "ambiguous_count": sum(1 for row in case_reference_audit_records if row.get("resolution_status") == "ambiguous"),
        "unresolved_external_count": sum(
            1 for row in case_reference_audit_records if row.get("resolution_status") == "unresolved_external"
        ),
    }

    case_to_case_count = sum(1 for r in relation_records if r.get("relation_model") == "case_to_case")
    law_to_law_count = sum(1 for r in relation_records if r.get("relation_model") == "law_to_law")
    law_to_case_count = sum(1 for r in relation_records if r.get("relation_model") == "law_to_case")

    manifest = {
        "legal_corpus_count": len(legal_corpus_records),
        "legal_relations_count": len(relation_records),
        "law_to_case_count": law_to_case_count,
        "law_to_law_count": law_to_law_count,
        "case_to_case_count": case_to_case_count,
        "law_record_count": len(law_records),
        "related_doc_record_count": len(related_records),
        "case_reference_audit_manifest": case_reference_audit_manifest,
        "appendix_dataset_manifest": appendix_manifest,
        "article_appendix_manifest": article_appendix_manifest,
        "merge_appendices_into_law_article": merge_appendices_into_law_article,
        "include_appendix_bundle_text_in_payload": include_appendix_bundle_text_in_payload,
        "write_legacy_appendix_datasets": write_legacy_appendix_datasets,
        "include_law_to_law_relations": include_law_to_law_relations,
        "max_chars": max_chars,
        "overlap": overlap,
        "text_variant": text_variant,
        "preserve_structure": preserve_structure,
        "include_non_searchable_law_parts": include_non_searchable_law_parts,
    }

    _write_json(output_dir / "dataset_manifest.json", manifest)

    return manifest


def _rows_by_id(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            continue
        indexed[row_id] = dict(row)
    return indexed


def _infer_collection_name(row: dict[str, Any], *, relation_file: bool) -> str:
    if relation_file:
        return "legal_relation"
    return "law_article" if str(row.get("doc_type") or "").strip() == "law" else "legal_case"


def _annotate_point_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(row) for row in rows]
    duplicates = duplicate_canonical_ids(rows)
    for row in rows:
        row["_point_id"] = build_qdrant_point_id(row, duplicates)
    return rows


def build_incremental_dataset_patch(
    *,
    previous_corpus_rows: list[dict[str, Any]],
    current_corpus_rows: list[dict[str, Any]],
    previous_relation_rows: list[dict[str, Any]],
    current_relation_rows: list[dict[str, Any]],
    patch_dir: str | Path,
    delta_batch_id: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    patch_dir = Path(patch_dir)
    updated_at = updated_at or _now_timestamp()

    previous_corpus_rows = _annotate_point_ids(previous_corpus_rows)
    current_corpus_rows = _annotate_point_ids(current_corpus_rows)
    previous_relation_rows = _annotate_point_ids(previous_relation_rows)
    current_relation_rows = _annotate_point_ids(current_relation_rows)

    previous_corpus = _rows_by_id(previous_corpus_rows)
    current_corpus = _rows_by_id(current_corpus_rows)
    previous_relations = _rows_by_id(previous_relation_rows)
    current_relations = _rows_by_id(current_relation_rows)

    def _build_patch(previous_rows: dict[str, dict[str, Any]], current_rows: dict[str, dict[str, Any]], *, relation_file: bool):
        upserts: list[dict[str, Any]] = []
        deletes: list[dict[str, Any]] = []

        current_ids = set(current_rows)
        previous_ids = set(previous_rows)

        for row_id in sorted(current_ids - previous_ids):
            row = dict(current_rows[row_id])
            row["collection_name"] = _infer_collection_name(row, relation_file=relation_file)
            row["delta_batch_id"] = delta_batch_id
            row["updated_at"] = updated_at
            upserts.append(row)

        for row_id in sorted(previous_ids & current_ids):
            previous_row = previous_rows[row_id]
            current_row = current_rows[row_id]
            if previous_row == current_row:
                continue
            row = dict(current_row)
            row["collection_name"] = _infer_collection_name(row, relation_file=relation_file)
            row["delta_batch_id"] = delta_batch_id
            row["updated_at"] = updated_at
            upserts.append(row)
            if str(previous_row.get("_point_id") or "") != str(current_row.get("_point_id") or ""):
                delete_row = dict(previous_row)
                delete_row["collection_name"] = _infer_collection_name(delete_row, relation_file=relation_file)
                delete_row["delta_batch_id"] = delta_batch_id
                delete_row["updated_at"] = updated_at
                deletes.append(delete_row)

        for row_id in sorted(previous_ids - current_ids):
            row = dict(previous_rows[row_id])
            row["collection_name"] = _infer_collection_name(row, relation_file=relation_file)
            row["delta_batch_id"] = delta_batch_id
            row["updated_at"] = updated_at
            deletes.append(row)

        return upserts, deletes

    corpus_upserts, corpus_deletes = _build_patch(previous_corpus, current_corpus, relation_file=False)
    relation_upserts, relation_deletes = _build_patch(previous_relations, current_relations, relation_file=True)

    write_jsonl(corpus_upserts, patch_dir / "legal_corpus.upsert.jsonl")
    write_jsonl(corpus_deletes, patch_dir / "legal_corpus.delete.jsonl")
    write_jsonl(relation_upserts, patch_dir / "legal_relations.upsert.jsonl")
    write_jsonl(relation_deletes, patch_dir / "legal_relations.delete.jsonl")

    manifest = {
        "delta_batch_id": delta_batch_id,
        "updated_at": updated_at,
        "legal_corpus_upsert_count": len(corpus_upserts),
        "legal_corpus_delete_count": len(corpus_deletes),
        "legal_relations_upsert_count": len(relation_upserts),
        "legal_relations_delete_count": len(relation_deletes),
    }
    _write_json(patch_dir / "delta_manifest.json", manifest)
    return manifest


def load_dataset_rows(output_dir: str | Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output_dir = Path(output_dir)
    return (
        list(_iter_jsonl(output_dir / "legal_corpus.jsonl")),
        list(_iter_jsonl(output_dir / "legal_relations.jsonl")),
    )
