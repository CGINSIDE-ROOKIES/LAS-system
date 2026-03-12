from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from src.collector.legal_doc_collector import (
    DETAIL_LINK_KEYS_BY_TARGET,
    DOC_TYPE_LABELS,
    ID_KEYS_BY_TARGET,
    NUMBER_KEYS_BY_TARGET,
    TARGET_CONFIGS,
    TITLE_KEYS_BY_TARGET,
    build_doc_ref,
    extract_list_items,
)
from src.common.io_utils import _read_json, _safe_filename, _write_json
from src.common.payload_utils import _first_non_empty, _walk_objects


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


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


def get_relation_rules(
    scope: dict[str, Any],
    file_id: str = "03_expanded_related_docs",
) -> list[str]:
    outputs = scope.get("outputs", [])
    if not isinstance(outputs, list):
        return ["related_law", "cited_law", "cited_case", "referenced_interpretation"]

    for output in outputs:
        if isinstance(output, dict) and output.get("file_id") == file_id:
            rules = output.get("relation_rules", [])
            if isinstance(rules, list) and rules:
                return [str(rule) for rule in rules]

    return ["related_law", "cited_law", "cited_case", "referenced_interpretation"]


def get_family_law_names(family_result: dict[str, Any]) -> list[str]:
    laws = family_result.get("laws", [])
    if not isinstance(laws, list):
        raise ValueError("family_result.laws must be a list")

    names: list[str] = []
    seen: set[str] = set()

    for law in laws:
        if not isinstance(law, dict):
            continue

        law_name = str(law.get("law_name") or "").strip()
        if not law_name or law_name in seen:
            continue

        seen.add(law_name)
        names.append(law_name)

    return names


def _build_law_name_folder_map(family_law_names: list[str]) -> dict[str, str]:
    return {_safe_filename(name): name for name in family_law_names}


def _extract_case_numbers(texts: list[str]) -> list[str]:
    pattern = re.compile(r"\b\d{2,4}[가-힣]{1,4}\d+\b")
    seen: set[str] = set()
    results: list[str] = []

    for text in texts:
        for match in pattern.findall(text):
            if match in seen:
                continue
            seen.add(match)
            results.append(match)

    return results


def _find_related_law_mentions(
    texts: list[str],
    family_law_names: list[str],
) -> list[str]:
    normalized_texts = [_normalize_name(text) for text in texts]

    matched: list[str] = []
    seen: set[str] = set()

    for law_name in family_law_names:
        normalized_law_name = _normalize_name(law_name)

        if any(normalized_law_name in text for text in normalized_texts):
            if law_name not in seen:
                seen.add(law_name)
                matched.append(law_name)

    return matched


def _collect_preview_text(texts: list[str], limit: int = 3) -> str:
    candidates = [text for text in texts if len(text) >= 20]
    if not candidates:
        candidates = texts[:limit]

    return "\n".join(candidates[:limit])


def _infer_relation_types(
    target: str,
    matched_law_names: list[str],
    cited_cases: list[str],
    enabled_rules: list[str],
) -> list[str]:
    relation_types: list[str] = []

    if matched_law_names:
        if "related_law" in enabled_rules:
            relation_types.append("related_law")
        if "cited_law" in enabled_rules:
            relation_types.append("cited_law")

    if cited_cases and "cited_case" in enabled_rules:
        relation_types.append("cited_case")

    if target == "expc" and "referenced_interpretation" in enabled_rules:
        relation_types.append("referenced_interpretation")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in relation_types:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)

    return deduped


def _extract_doc_meta_from_payload(target: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc_id = _find_first_recursive(payload, ID_KEYS_BY_TARGET[target])
    title = _find_first_recursive(payload, TITLE_KEYS_BY_TARGET[target])
    doc_number = _find_first_recursive(payload, NUMBER_KEYS_BY_TARGET[target])
    detail_link = _find_first_recursive(payload, DETAIL_LINK_KEYS_BY_TARGET[target])

    return {
        "doc_id": str(doc_id) if doc_id is not None else None,
        "title": str(title) if title is not None else None,
        "doc_number": str(doc_number) if doc_number is not None else None,
        "detail_link": str(detail_link) if detail_link is not None else None,
    }


def _build_embedding_text(record: dict[str, Any]) -> str:
    lines = [
        f"루트 법령: {record['root_law_name']}",
        f"문서 유형: {record['doc_type_label']}",
        f"문서 제목: {record.get('title') or ''}",
        f"문서 번호: {record.get('doc_number') or ''}",
        f"관련 법령: {', '.join(record.get('related_law_names', []))}",
        f"관계 유형: {', '.join(record.get('relation_types', []))}",
    ]

    cited_cases = record.get("cited_cases", [])
    if cited_cases:
        lines.append(f"추출된 참조 사건번호: {', '.join(cited_cases[:10])}")

    preview_text = record.get("preview_text")
    if preview_text:
        lines.append("원문 일부:")
        lines.append(preview_text)

    return "\n".join(lines).strip()


def _make_expanded_record(
    *,
    root_law_name: str,
    target: str,
    source_law_name: str,
    doc_meta: dict[str, Any],
    texts: list[str],
    family_law_names: list[str],
    relation_rules: list[str],
    source_file_path: str,
) -> dict[str, Any] | None:
    matched_law_names = _find_related_law_mentions(texts, family_law_names)
    cited_cases = _extract_case_numbers(texts)

    if not matched_law_names and source_law_name:
        matched_law_names = [source_law_name]

    relation_types = _infer_relation_types(
        target=target,
        matched_law_names=matched_law_names,
        cited_cases=cited_cases,
        enabled_rules=relation_rules,
    )

    if not matched_law_names and not cited_cases and not relation_types:
        return None

    preview_text = _collect_preview_text(texts)

    record = {
        "root_law_name": root_law_name,
        "source_law_name": source_law_name,
        "target": target,
        "doc_type_label": DOC_TYPE_LABELS[target],
        "doc_id": doc_meta.get("doc_id"),
        "title": doc_meta.get("title"),
        "doc_number": doc_meta.get("doc_number"),
        "detail_link": doc_meta.get("detail_link"),
        "related_law_names": matched_law_names,
        "relation_types": relation_types,
        "cited_cases": cited_cases,
        "preview_text": preview_text,
        "source_file_path": source_file_path,
    }
    record["embedding_text"] = _build_embedding_text(record)
    return record


def _expand_detail_payload(
    *,
    root_law_name: str,
    target: str,
    source_law_name: str,
    payload: dict[str, Any],
    family_law_names: list[str],
    relation_rules: list[str],
    source_file_path: str,
) -> dict[str, Any] | None:
    doc_meta = _extract_doc_meta_from_payload(target, payload)
    texts = list(_walk_strings(payload))
    return _make_expanded_record(
        root_law_name=root_law_name,
        target=target,
        source_law_name=source_law_name,
        doc_meta=doc_meta,
        texts=texts,
        family_law_names=family_law_names,
        relation_rules=relation_rules,
        source_file_path=source_file_path,
    )


def _expand_list_item_ref(
    *,
    root_law_name: str,
    target: str,
    source_law_name: str,
    ref: dict[str, Any],
    family_law_names: list[str],
    relation_rules: list[str],
    source_file_path: str,
) -> dict[str, Any] | None:
    raw_item = ref.get("raw_item", {})
    if not isinstance(raw_item, dict):
        raw_item = {}

    texts = list(_walk_strings(raw_item))

    doc_meta = {
        "doc_id": ref.get("doc_id"),
        "title": ref.get("title"),
        "doc_number": ref.get("doc_number"),
        "detail_link": ref.get("detail_link"),
    }

    return _make_expanded_record(
        root_law_name=root_law_name,
        target=target,
        source_law_name=source_law_name,
        doc_meta=doc_meta,
        texts=texts,
        family_law_names=family_law_names,
        relation_rules=relation_rules,
        source_file_path=source_file_path,
    )


def collect_expanded_related_docs_for_family_result(
    scope: dict[str, Any],
    family_result: dict[str, Any],
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    save_dir: str | Path = "data/expanded/03_expanded_related_docs",
    targets: list[str] | None = None,
    max_records_per_target: int = 50,
) -> dict[str, Any]:
    selected_targets = targets or list(TARGET_CONFIGS.keys())

    root_law_name = str(family_result.get("root_law_name") or "").strip()
    if not root_law_name:
        raise ValueError("family_result.root_law_name is required")

    family_law_names = get_family_law_names(family_result)
    relation_rules = get_relation_rules(scope)

    raw_root_dir = Path(raw_related_base_dir) / _safe_filename(root_law_name)
    save_root_dir = Path(save_dir) / _safe_filename(root_law_name)

    law_name_folder_map = _build_law_name_folder_map(family_law_names)

    result = {
        "root_law_name": root_law_name,
        "family_law_names": family_law_names,
        "relation_rules": relation_rules,
        "targets": {},
        "expanded_count": 0,
        "records": [],
        "errors": [],
    }

    seen_records: set[str] = set()

    for target in selected_targets:
        if target not in TARGET_CONFIGS:
            result["targets"][target] = {
                "detail_supported": False,
                "source_file_count": 0,
                "expanded_count": 0,
            }
            continue

        target_dir = raw_root_dir / target
        detail_supported = TARGET_CONFIGS[target]["detail_endpoint"] is not None
        target_summary = {
            "detail_supported": detail_supported,
            "source_file_count": 0,
            "expanded_count": 0,
        }

        if not target_dir.exists():
            result["targets"][target] = target_summary
            continue

        expanded_for_target = 0

        if detail_supported:
            files = sorted(target_dir.rglob("*__detail.json"))
            target_summary["source_file_count"] = len(files)

            for path in files:
                if expanded_for_target >= max_records_per_target:
                    break

                try:
                    payload = _read_json(path)
                    source_folder = path.parent.name
                    source_law_name = law_name_folder_map.get(source_folder, source_folder)

                    record = _expand_detail_payload(
                        root_law_name=root_law_name,
                        target=target,
                        source_law_name=source_law_name,
                        payload=payload,
                        family_law_names=family_law_names,
                        relation_rules=relation_rules,
                        source_file_path=str(path),
                    )
                except Exception as exc:
                    result["errors"].append(
                        {
                            "target": target,
                            "source_file_path": str(path),
                            "message": str(exc),
                        }
                    )
                    continue

                if record is None:
                    continue

                dedup_key = "|".join(
                    [
                        str(record.get("target") or ""),
                        str(record.get("doc_id") or ""),
                        str(record.get("title") or ""),
                        ",".join(record.get("related_law_names", [])),
                    ]
                )
                if dedup_key in seen_records:
                    continue

                seen_records.add(dedup_key)
                expanded_for_target += 1
                result["records"].append(record)

                doc_id = str(record.get("doc_id") or "")
                doc_stem = f"{target}_{doc_id or expanded_for_target}"
                _write_json(
                    save_root_dir / target / f"{doc_stem}__expanded.json",
                    record,
                )

        else:
            list_files = sorted(target_dir.rglob("*__list.json"))
            target_summary["source_file_count"] = len(list_files)

            for path in list_files:
                if expanded_for_target >= max_records_per_target:
                    break

                try:
                    payload = _read_json(path)
                    source_folder = path.parent.name
                    source_law_name = law_name_folder_map.get(source_folder, source_folder)
                    items = extract_list_items(payload, target)
                except Exception as exc:
                    result["errors"].append(
                        {
                            "target": target,
                            "source_file_path": str(path),
                            "message": str(exc),
                        }
                    )
                    continue

                for item in items:
                    if expanded_for_target >= max_records_per_target:
                        break

                    ref = build_doc_ref(target, source_law_name, item)
                    record = _expand_list_item_ref(
                        root_law_name=root_law_name,
                        target=target,
                        source_law_name=source_law_name,
                        ref=ref,
                        family_law_names=family_law_names,
                        relation_rules=relation_rules,
                        source_file_path=str(path),
                    )
                    if record is None:
                        continue

                    dedup_key = "|".join(
                        [
                            str(record.get("target") or ""),
                            str(record.get("doc_id") or ""),
                            str(record.get("title") or ""),
                            ",".join(record.get("related_law_names", [])),
                        ]
                    )
                    if dedup_key in seen_records:
                        continue

                    seen_records.add(dedup_key)
                    expanded_for_target += 1
                    result["records"].append(record)

                    doc_id = str(record.get("doc_id") or "")
                    doc_stem = f"{target}_{doc_id or expanded_for_target}"

                    _write_json(
                        save_root_dir / target / f"{doc_stem}__expanded.json",
                        record,
                    )

        target_summary["expanded_count"] = expanded_for_target
        result["targets"][target] = target_summary

    result["expanded_count"] = len(result["records"])

    _write_json(
        save_root_dir / f"{_safe_filename(root_law_name)}__expanded_manifest.json",
        result,
    )

    return result
