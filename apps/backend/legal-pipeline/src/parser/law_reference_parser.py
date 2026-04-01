"""Parse law article references for `law_to_law` relation building.

Observed relation examples from the current dataset:
- `explicit_law_article`: `민법 제750조`
- `relative_scope`: `같은 법 제9조`, noisy fallback like `제43조(하도급계약의 특례) 법 제48조`
- `previous_article` / `current_article`: `전조`, `동조`
- `same_law_article`: `제7조부터 제9조까지`
"""

from __future__ import annotations

import re
from typing import Any

from src.common.law_meta import normalize_classified_level

ARTICLE_PATTERN = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
ARTICLE_RANGE_PATTERN = re.compile(
    r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:부터|내지)\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:까지)?"
)
ARTICLE_BLOCK_PATTERN = (
    r"제\s*\d+\s*조(?:\s*의\s*\d+)?"
    r"(?:\s*(?:부터|내지)\s*제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:까지)?)?"
    r"(?:\s*(?:,|및|와|과|또는|혹은|·)\s*제\s*\d+\s*조(?:\s*의\s*\d+)?)*"
)
SINGLE_ARTICLE_BLOCK_PATTERN = (
    r"제\s*\d+\s*조(?:\s*의\s*\d+)?"
    r"(?:\s*(?:부터|내지)\s*제\s*\d+\s*조(?:\s*의\s*\d+)?\s*(?:까지)?)?"
)
LAW_NAME_TOKEN_PATTERN = r"(?!및\b|또는\b|혹은\b|와\b|과\b|전조\b|동조\b|같은\b|이\b)[가-힣0-9·ㆍ()]+"
EXPLICIT_LAW_WITH_ARTICLE_PATTERN = re.compile(
    rf"(?<![가-힣0-9])(?P<law_name>{LAW_NAME_TOKEN_PATTERN}(?:\s+{LAW_NAME_TOKEN_PATTERN}){{0,7}})\s*(?P<article_block>{ARTICLE_BLOCK_PATTERN})"
)
RELATIVE_SCOPE_WITH_ARTICLE_PATTERN = re.compile(
    r"(?P<prefix>이|같은|동)\s*(?P<scope>법|영|규칙|조례)\s*"
    rf"(?P<article_block>{SINGLE_ARTICLE_BLOCK_PATTERN})"
)
BARE_ARTICLE_BLOCK_PATTERN = re.compile(
    rf"(?<![가-힣0-9])(?P<article_block>{ARTICLE_BLOCK_PATTERN})"
)
RELATIVE_ARTICLE_PATTERNS = {
    "previous_article": re.compile(r"전\s*조"),
    "next_article": re.compile(r"다음\s*조"),
    "current_article": re.compile(r"같은\s*조|동\s*조"),
}


def _normalize_space(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _looks_like_law_name(text: str) -> bool:
    candidate = _normalize_space(text)
    if not candidate:
        return False
    if candidate in {"이 법", "같은 법", "이 영", "같은 영", "이 규칙", "같은 규칙", "이 조례", "같은 조례"}:
        return False
    return candidate.endswith(("법", "법률", "시행령", "대통령령", "령", "시행규칙", "규칙", "부령", "조례", "규정", "훈령", "예규", "고시"))


def _is_noisy_explicit_law_name(text: str) -> bool:
    candidate = _normalize_space(text)
    if not candidate:
        return True

    if re.match(r"^제\s*\d+\s*조(?:\s*의\s*\d+)?", candidate):
        return True

    if "(" in candidate or ")" in candidate:
        return True

    if candidate in {"법", "법 시행령", "법 시행규칙", "같은 법 시행령", "같은 법 시행규칙"}:
        return True

    tokens = candidate.split()
    if len(tokens) >= 2 and tokens[0] == "법":
        return True

    if len(tokens) >= 4 and candidate.endswith("법"):
        return True

    topic_particles = ("은", "는", "이", "가")
    object_particles = ("을", "를")
    conjunctive_particles = ("과", "와")
    institutional_suffixes = ("장관", "위원회", "청장", "협회", "원장", "시장", "군수", "구청장", "도지사")

    for token in tokens[:-1]:
        if token.endswith(topic_particles + object_particles + conjunctive_particles):
            return True
        if token.endswith(institutional_suffixes):
            return True

    return False


def _infer_scope_from_noisy_candidate(text: str) -> str | None:
    candidate = _normalize_space(text)
    if not candidate or not _is_noisy_explicit_law_name(candidate):
        return None

    suffix_to_scope = (
        ("시행규칙", "규칙"),
        ("부령", "규칙"),
        ("규칙", "규칙"),
        ("시행령", "영"),
        ("대통령령", "영"),
        ("령", "영"),
        ("법률", "법"),
        ("법", "법"),
        ("조례", "조례"),
    )
    for suffix, scope in suffix_to_scope:
        if candidate.endswith(suffix):
            return scope
    return None


def _article_ref(main_no: str, branch_no: str | None) -> dict[str, str]:
    article_key = str(int(main_no)) if not branch_no else f"{int(main_no)}-{int(branch_no)}"
    article_no_display = f"제{int(main_no)}조" if not branch_no else f"제{int(main_no)}조의{int(branch_no)}"
    return {
        "article_key": article_key,
        "article_no_display": article_no_display,
    }


def _expand_article_range(start: tuple[str, str | None], end: tuple[str, str | None]) -> list[dict[str, str]]:
    start_main, start_branch = start
    end_main, end_branch = end
    if start_branch is None and end_branch is None:
        start_no = int(start_main)
        end_no = int(end_main)
        if start_no <= end_no:
            return [_article_ref(str(article_no), None) for article_no in range(start_no, end_no + 1)]
    if start_main == end_main and start_branch is not None and end_branch is not None:
        start_no = int(start_branch)
        end_no = int(end_branch)
        if start_no <= end_no:
            return [_article_ref(start_main, str(branch_no)) for branch_no in range(start_no, end_no + 1)]
    return [_article_ref(start_main, start_branch), _article_ref(end_main, end_branch)]


def extract_article_refs(article_block: str) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()

    for match in ARTICLE_RANGE_PATTERN.finditer(article_block):
        for article in _expand_article_range(match.group(1, 2), match.group(3, 4)):
            if article["article_key"] in seen:
                continue
            seen.add(article["article_key"])
            refs.append(article)

    for match in ARTICLE_PATTERN.finditer(article_block):
        article = _article_ref(match.group(1), match.group(2))
        if article["article_key"] in seen:
            continue
        seen.add(article["article_key"])
        refs.append(article)

    return refs


def _mask_span(text: str, start: int, end: int) -> str:
    return text[:start] + (" " * max(0, end - start)) + text[end:]


def _article_order_index(article_order: list[dict[str, str]]) -> dict[str, int]:
    return {
        str(item.get("article_key") or "").strip(): index
        for index, item in enumerate(article_order)
        if str(item.get("article_key") or "").strip()
    }


def _resolve_relative_article(
    relation_kind: str,
    *,
    source_article_key: str | None,
    article_order: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not source_article_key:
        return []

    index_by_key = _article_order_index(article_order)
    current_index = index_by_key.get(str(source_article_key).strip())
    if current_index is None:
        return []

    target_index = current_index
    if relation_kind == "previous_article":
        target_index = current_index - 1
    elif relation_kind == "next_article":
        target_index = current_index + 1

    if target_index < 0 or target_index >= len(article_order):
        return []

    target = article_order[target_index]
    article_key = str(target.get("article_key") or "").strip()
    article_no_display = str(target.get("article_no_display") or "").strip()
    if not article_key:
        return []

    return [{"article_key": article_key, "article_no_display": article_no_display or article_key}]


def _build_family_alias_map(
    *,
    root_law_name: str,
    family_laws: list[dict[str, Any]],
) -> dict[str, list[str]]:
    alias_map: dict[str, list[str]] = {}

    def add_alias(alias: str, law_name: str) -> None:
        key = _normalize_name(alias)
        value = str(law_name or "").strip()
        if not key or not value:
            return
        alias_map.setdefault(key, [])
        if value not in alias_map[key]:
            alias_map[key].append(value)

    for law in family_laws:
        law_name = str(law.get("law_name") or "").strip()
        if not law_name:
            continue

        add_alias(law_name, law_name)
        suffix = law_name
        if root_law_name and law_name.startswith(root_law_name):
            suffix = law_name[len(root_law_name):].strip()
        if suffix and suffix != law_name:
            add_alias(suffix, law_name)

        level = normalize_classified_level(law.get("kind_name"), law.get("classified_level"))
        if level in {"법", "시행령", "시행규칙"}:
            add_alias(level, law_name)

    return alias_map


def _resolve_scope_target_law_names(
    *,
    scope: str,
    source_law_name: str,
    source_law_level: str | None,
    root_law_name: str,
    family_laws: list[dict[str, Any]],
) -> list[str]:
    desired_level = {
        "법": "법",
        "영": "시행령",
        "규칙": "시행규칙",
        "조례": "조례",
    }.get(scope, scope)

    source_level = normalize_classified_level(None, source_law_level)
    if source_level == desired_level and source_law_name:
        return [source_law_name]

    if desired_level == "법" and root_law_name:
        for law in family_laws:
            law_name = str(law.get("law_name") or "").strip()
            if law_name == root_law_name:
                return [law_name]

    resolved: list[str] = []
    for law in family_laws:
        law_name = str(law.get("law_name") or "").strip()
        if not law_name:
            continue
        level = normalize_classified_level(law.get("kind_name"), law.get("classified_level"))
        if level != desired_level:
            continue
        if desired_level == "법" and root_law_name and law_name == root_law_name:
            return [law_name]
        if law_name not in resolved:
            resolved.append(law_name)
    return resolved


def _resolve_law_name_candidates(
    candidate_law_name: str,
    *,
    root_law_name: str,
    source_law_name: str,
    source_law_level: str | None,
    family_laws: list[dict[str, Any]],
) -> tuple[list[str], str]:
    normalized = _normalize_name(candidate_law_name)
    alias_map = _build_family_alias_map(root_law_name=root_law_name, family_laws=family_laws)
    candidates = alias_map.get(normalized, [])
    if not candidates:
        return [], "unresolved_external"
    if len(candidates) == 1:
        return candidates, "resolved"
    scope_candidates = _resolve_scope_target_law_names(
        scope=normalized,
        source_law_name=source_law_name,
        source_law_level=source_law_level,
        root_law_name=root_law_name,
        family_laws=family_laws,
    )
    if len(scope_candidates) == 1:
        return scope_candidates, "resolved"
    return candidates, "ambiguous"


def _append_reference(
    results: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    reference_type: str,
    reference_text: str,
    target_law_name: str | None,
    related_law_names: list[str] | None,
    article_refs: list[dict[str, str]],
    resolution_status: str,
    resolution_confidence: float,
) -> None:
    article_keys = [item["article_key"] for item in article_refs]
    article_no_displays = [item["article_no_display"] for item in article_refs]
    dedup_key = (
        reference_type,
        str(target_law_name or "").strip(),
        "|".join(article_keys) or _normalize_space(reference_text),
    )
    if dedup_key in seen:
        return
    seen.add(dedup_key)
    results.append(
        {
            "reference_type": reference_type,
            "reference_text": _normalize_space(reference_text),
            "target_law_name": str(target_law_name or "").strip() or None,
            "related_law_names": list(dict.fromkeys([name for name in related_law_names or [] if str(name).strip()])),
            "target_article_keys": article_keys,
            "target_article_no_displays": article_no_displays,
            "resolution_status": resolution_status,
            "resolution_confidence": resolution_confidence,
        }
    )


def parse_law_article_references(
    text: str,
    *,
    source_law_name: str,
    source_law_level: str | None,
    source_article_key: str | None,
    article_order: list[dict[str, str]],
    root_law_name: str,
    family_laws: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_text = str(text or "")
    masked_text = raw_text
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for match in RELATIVE_SCOPE_WITH_ARTICLE_PATTERN.finditer(raw_text):
        article_refs = extract_article_refs(match.group("article_block"))
        if not article_refs:
            continue
        candidates = _resolve_scope_target_law_names(
            scope=match.group("scope"),
            source_law_name=source_law_name,
            source_law_level=source_law_level,
            root_law_name=root_law_name,
            family_laws=family_laws,
        )
        resolution_status = "resolved" if len(candidates) == 1 else "ambiguous"
        target_law_name = candidates[0] if len(candidates) == 1 else None
        _append_reference(
            results,
            seen,
            reference_type="relative_scope",
            reference_text=match.group(0),
            target_law_name=target_law_name,
            related_law_names=candidates,
            article_refs=article_refs,
            resolution_status=resolution_status,
            resolution_confidence=0.9 if resolution_status == "resolved" else 0.6,
        )
        masked_text = _mask_span(masked_text, match.start(), match.end())

    for match in EXPLICIT_LAW_WITH_ARTICLE_PATTERN.finditer(raw_text):
        candidate_law_name = _normalize_space(match.group("law_name"))
        article_refs = extract_article_refs(match.group("article_block"))
        if not candidate_law_name or not article_refs or not _looks_like_law_name(candidate_law_name):
            continue

        inferred_scope = _infer_scope_from_noisy_candidate(candidate_law_name)
        if inferred_scope:
            candidates = _resolve_scope_target_law_names(
                scope=inferred_scope,
                source_law_name=source_law_name,
                source_law_level=source_law_level,
                root_law_name=root_law_name,
                family_laws=family_laws,
            )
            resolution_status = "resolved" if len(candidates) == 1 else "ambiguous"
            target_law_name = candidates[0] if len(candidates) == 1 else None
            _append_reference(
                results,
                seen,
                reference_type="relative_scope",
                reference_text=match.group(0),
                target_law_name=target_law_name,
                related_law_names=candidates,
                article_refs=article_refs,
                resolution_status=resolution_status,
                resolution_confidence=0.88 if resolution_status == "resolved" else 0.55,
            )
            masked_text = _mask_span(masked_text, match.start(), match.end())
            continue

        if _is_noisy_explicit_law_name(candidate_law_name):
            continue

        candidates, resolution_status = _resolve_law_name_candidates(
            candidate_law_name,
            root_law_name=root_law_name,
            source_law_name=source_law_name,
            source_law_level=source_law_level,
            family_laws=family_laws,
        )
        target_law_name = candidates[0] if resolution_status == "resolved" and len(candidates) == 1 else candidate_law_name
        _append_reference(
            results,
            seen,
            reference_type="explicit_law_article",
            reference_text=match.group(0),
            target_law_name=target_law_name,
            related_law_names=candidates if resolution_status != "unresolved_external" else [candidate_law_name],
            article_refs=article_refs,
            resolution_status=resolution_status,
            resolution_confidence=0.95 if resolution_status == "resolved" else 0.45,
        )
        masked_text = _mask_span(masked_text, match.start(), match.end())

    for reference_type, pattern in RELATIVE_ARTICLE_PATTERNS.items():
        for match in pattern.finditer(masked_text):
            article_refs = _resolve_relative_article(
                reference_type,
                source_article_key=source_article_key,
                article_order=article_order,
            )
            if not article_refs:
                continue
            _append_reference(
                results,
                seen,
                reference_type=reference_type,
                reference_text=match.group(0),
                target_law_name=source_law_name,
                related_law_names=[source_law_name],
                article_refs=article_refs,
                resolution_status="resolved",
                resolution_confidence=0.92,
            )
            masked_text = _mask_span(masked_text, match.start(), match.end())

    for match in BARE_ARTICLE_BLOCK_PATTERN.finditer(masked_text):
        article_refs = extract_article_refs(match.group("article_block"))
        if not article_refs:
            continue
        _append_reference(
            results,
            seen,
            reference_type="same_law_article",
            reference_text=match.group("article_block"),
            target_law_name=source_law_name,
            related_law_names=[source_law_name],
            article_refs=article_refs,
            resolution_status="resolved",
            resolution_confidence=0.9,
        )

    return results
