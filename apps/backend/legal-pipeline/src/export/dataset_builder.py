from __future__ import annotations

import re
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
from src.common.io_utils import _read_json, _write_json
from src.common.payload_utils import _first_non_empty, _walk_objects
from src.export.jsonl_builder import write_jsonl

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


def _normalize_law_text(text: str, *, preserve_structure: bool) -> str:
    return _normalize_structure(text) if preserve_structure else _normalize_space(text)


def _article_display_no(article: dict[str, Any]) -> str:
    return str(
        article.get("article_no_display")
        or article.get("article_no")
        or article.get("jo_code")
        or ""
    ).strip()


def _article_record_key(article: dict[str, Any]) -> str:
    return str(
        article.get("jo_code")
        or article.get("article_key")
        or article.get("article_no_display")
        or article.get("article_no")
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
        lines.append(text)

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


def build_law_records(
    normalized_base_dir: str | Path = "data/normalized/01_current_law",
    max_chars: int = 1200,
    overlap: int = 150,
    *,
    text_variant: TextVariant = "best",
    preserve_structure: bool = True,
    include_non_searchable_law_parts: bool = False,
) -> list[dict[str, Any]]:
    base_dir = Path(normalized_base_dir)
    records: list[dict[str, Any]] = []

    for path in sorted(base_dir.rglob("*__parsed_law.json")):
        parsed_law = _read_json(path)

        law_name = str(parsed_law.get("law_name") or "").strip()
        law_id = parsed_law.get("law_id")
        mst = parsed_law.get("mst")
        ef_yd = parsed_law.get("ef_yd")
        kind_name = parsed_law.get("kind_name")
        classified_level = parsed_law.get("classified_level")
        scope_source = parsed_law.get("scope_source")

        articles = parsed_law.get("articles", [])
        if isinstance(articles, list):
            for article in articles:
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
                chunks = _chunk_text(
                    article_text,
                    max_chars=max_chars,
                    overlap=overlap,
                    preserve_structure=preserve_structure,
                )

                for chunk_index, chunk in enumerate(chunks):
                    record_id = "::".join(
                        [
                            "law",
                            law_name or "unknown",
                            str(article_key or chunk_index),
                            str(chunk_index),
                        ]
                    )

                    records.append(
                        {
                            "id": record_id,
                            "text": chunk,
                            "doc_type": "law",
                            "section_type": "article",
                            "source_group": "01_current_law",
                            "law_name": law_name,
                            "law_id": law_id,
                            "mst": mst,
                            "ef_yd": ef_yd,
                            "kind_name": kind_name,
                            "classified_level": classified_level,
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
                chunks = _chunk_text(
                    text,
                    max_chars=max_chars,
                    overlap=overlap,
                    preserve_structure=preserve_structure,
                )

                for chunk_index, chunk in enumerate(chunks):
                    record_id = "::".join(
                        [
                            "law",
                            law_name or "unknown",
                            "supplementary",
                            str(item_index),
                            str(chunk_index),
                        ]
                    )
                    records.append(
                        {
                            "id": record_id,
                            "text": chunk,
                            "doc_type": "law",
                            "section_type": "supplementary",
                            "source_group": "01_current_law",
                            "law_name": law_name,
                            "law_id": law_id,
                            "mst": mst,
                            "ef_yd": ef_yd,
                            "kind_name": kind_name,
                            "classified_level": classified_level,
                            "scope_source": scope_source,
                            "supplementary_no": supplementary.get("supplementary_no"),
                            "supplementary_title": supplementary.get("supplementary_title"),
                            "content_category": _aux_part_content_category(supplementary),
                            "is_searchable": _is_searchable_aux_part(supplementary),
                            "chunk_index": chunk_index,
                            "text_variant": text_variant,
                            "structure_preserved": preserve_structure,
                            "source_file_path": str(path),
                        }
                    )

        appendices = parsed_law.get("appendices", [])
        if isinstance(appendices, list):
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
                    record_id = "::".join(
                        [
                            "law",
                            law_name or "unknown",
                            "appendix",
                            str(item_index),
                            str(chunk_index),
                        ]
                    )
                    records.append(
                        {
                            "id": record_id,
                            "text": chunk,
                            "doc_type": "law",
                            "section_type": "appendix",
                            "source_group": "01_current_law",
                            "law_name": law_name,
                            "law_id": law_id,
                            "mst": mst,
                            "ef_yd": ef_yd,
                            "kind_name": kind_name,
                            "classified_level": classified_level,
                            "scope_source": scope_source,
                            "appendix_title": appendix.get("appendix_title"),
                            "content_category": _aux_part_content_category(appendix),
                            "is_searchable": _is_searchable_aux_part(appendix),
                            "chunk_index": chunk_index,
                            "text_variant": text_variant,
                            "structure_preserved": preserve_structure,
                            "source_file_path": str(path),
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
        "detail_link": str(detail_link) if detail_link is not None else None,
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

        records.append(
            {
                "id": record_id,
                "text": full_text,
                "doc_type": target,
                "doc_type_label": DOC_TYPE_LABELS[target],
                "source_group": "02_related_legal_docs",
                "root_law_name": root_law_name,
                "related_law_name": source_law_name,
                "doc_id": doc_meta.get("doc_id"),
                "title": doc_meta.get("title"),
                "doc_number": doc_meta.get("doc_number"),
                "detail_link": doc_meta.get("detail_link"),
                "doc_kind": doc_meta.get("doc_kind"),
                "chunk_index": chunk_index,
                "source_file_path": source_file_path,
            }
        )

    return records


def build_related_doc_records(
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


def build_relation_records(
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
                "text": text,
                "doc_type": "relation",
                "source_group": "03_expanded_related_docs",
                "target": payload.get("target"),
                "doc_type_label": payload.get("doc_type_label"),
                "root_law_name": payload.get("root_law_name"),
                "source_law_name": payload.get("source_law_name"),
                "related_law_names": payload.get("related_law_names", []),
                "relation_types": payload.get("relation_types", []),
                "doc_id": payload.get("doc_id"),
                "title": payload.get("title"),
                "doc_number": payload.get("doc_number"),
                "source_file_path": str(path),
            }
        )

    return records


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
) -> dict[str, Any]:
    output_dir = Path(output_dir)

    law_records = build_law_records(
        normalized_base_dir=normalized_base_dir,
        max_chars=max_chars,
        overlap=overlap,
        text_variant=text_variant,
        preserve_structure=preserve_structure,
        include_non_searchable_law_parts=include_non_searchable_law_parts,
    )
    related_records = build_related_doc_records(
        raw_related_base_dir=raw_related_base_dir,
        max_chars=max_chars,
        overlap=overlap,
    )
    relation_records = build_relation_records(
        expanded_base_dir=expanded_base_dir,
    )

    appendix_manifest: dict[str, Any] | None = None
    if normalized_appendix_base_dir is not None:
        from src.export.appendix_dataset_builder import build_and_write_appendix_datasets

        appendix_manifest = build_and_write_appendix_datasets(
            normalized_appendix_base_dir=normalized_appendix_base_dir,
            output_dir=output_dir,
            max_chars=max_chars,
            overlap=overlap,
            normalized_appendix_asset_base_dir=normalized_appendix_asset_base_dir,
        )

    legal_corpus_records = law_records + related_records

    write_jsonl(legal_corpus_records, output_dir / "legal_corpus.jsonl")
    write_jsonl(relation_records, output_dir / "legal_relations.jsonl")

    manifest = {
        "legal_corpus_count": len(legal_corpus_records),
        "legal_relations_count": len(relation_records),
        "law_record_count": len(law_records),
        "related_doc_record_count": len(related_records),
        "appendix_dataset_manifest": appendix_manifest,
        "max_chars": max_chars,
        "overlap": overlap,
        "text_variant": text_variant,
        "preserve_structure": preserve_structure,
        "include_non_searchable_law_parts": include_non_searchable_law_parts,
    }

    _write_json(output_dir / "dataset_manifest.json", manifest)

    return manifest
