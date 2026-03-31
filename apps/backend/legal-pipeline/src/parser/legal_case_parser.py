from __future__ import annotations

import re
from typing import Any, Iterable

from src.collector.legal_doc_collector import (
    DETAIL_LINK_KEYS_BY_TARGET,
    DOC_KIND_KEYS,
    DOC_TYPE_LABELS,
    ID_KEYS_BY_TARGET,
    NUMBER_KEYS_BY_TARGET,
    TEXT_KEYS_BY_TARGET,
    TITLE_KEYS_BY_TARGET,
    build_canonical_case_id,
)
from src.common.url_utils import sanitize_detail_link, sanitize_inline_urls
from src.common.payload_utils import _first_non_empty, _walk_objects

DECISION_DATE_KEYS_BY_TARGET = {
    "prec": ("선고일자", "판결일자", "선고일"),
    "detc": ("종국일자", "선고일자", "결정일자", "선고일"),
    "expc": ("회신일자", "해석일자", "등록일자", "생산일자", "작성일자"),
    "decc": ("재결일자", "의결일자", "결정일자"),
}

BODY_SECTION_KEYS_BY_TARGET = {
    "prec": (
        ("판시사항", ("판시사항",)),
        ("판결요지", ("판결요지",)),
        ("참조조문", ("참조조문",)),
        ("참조판례", ("참조판례",)),
        ("판례내용", ("판례내용",)),
    ),
    "detc": (
        ("판시사항", ("판시사항",)),
        ("결정요지", ("결정요지",)),
        ("심판대상조문", ("심판대상조문",)),
        ("참조조문", ("참조조문",)),
        ("참조판례", ("참조판례",)),
        ("전문", ("전문",)),
    ),
    "expc": (
        ("질의요지", ("질의요지",)),
        ("회답", ("회답",)),
        ("이유", ("이유",)),
    ),
    "decc": (
        ("청구취지", ("청구취지",)),
        ("주문", ("주문",)),
        ("재결요지", ("재결요지",)),
        ("이유", ("이유",)),
    ),
}

CASE_REFERENCE_KEYS_BY_TARGET = {
    "prec": ("참조판례",),
    "detc": ("참조판례",),
    "expc": (),
    "decc": (),
}

GENERIC_TEXT_KEYS = (
    "전문",
    "본문",
    "내용",
    "판례내용",
    "판결요지",
    "판시사항",
    "결정요지",
    "회답",
    "해석내용",
    "답변",
    "주문",
    "이유",
    "재결요지",
)



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



def _normalize_name(text: str) -> str:
    return re.sub(r"\s+", "", text or "")



def _walk_strings(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "html":
                continue
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_strings(item)
    elif isinstance(node, str):
        text = _normalize_structure(node)
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



def _find_all_recursive(node: Any, keys: tuple[str, ...]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for obj in _walk_objects(node):
        if not isinstance(obj, dict):
            continue
        value = _first_non_empty(obj, *keys)
        if value in (None, "", []):
            continue
        text = _normalize_structure(str(value))
        if not text or text in seen:
            continue
        seen.add(text)
        results.append(text)

    return results



def _dedup_texts(texts: list[str]) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for text in texts:
        normalized = _normalize_structure(text)
        if not normalized:
            continue
        key = _normalize_space(normalized)
        if key in seen:
            continue
        seen.add(key)
        results.append(normalized)

    return results



def extract_case_meta(
    target: str,
    payload: dict[str, Any],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = fallback or {}
    doc_id = _find_first_recursive(payload, ID_KEYS_BY_TARGET[target]) or fallback.get("doc_id")
    title = _find_first_recursive(payload, TITLE_KEYS_BY_TARGET[target]) or fallback.get("title")
    doc_number = _find_first_recursive(payload, NUMBER_KEYS_BY_TARGET[target]) or fallback.get("doc_number")
    detail_link = _find_first_recursive(payload, DETAIL_LINK_KEYS_BY_TARGET[target]) or fallback.get("detail_link")
    doc_kind = _find_first_recursive(payload, DOC_KIND_KEYS) or fallback.get("doc_kind")
    decision_date = _find_first_recursive(payload, DECISION_DATE_KEYS_BY_TARGET[target]) or fallback.get("decision_date")
    canonical_case_id = build_canonical_case_id(target, doc_id, doc_number, title)

    return {
        "canonical_case_id": canonical_case_id,
        "canonical_id": canonical_case_id,
        "target": target,
        "doc_type_label": DOC_TYPE_LABELS[target],
        "doc_id": str(doc_id) if doc_id not in (None, "") else None,
        "title": str(title) if title not in (None, "") else None,
        "doc_number": str(doc_number) if doc_number not in (None, "") else None,
        "doc_kind": str(doc_kind) if doc_kind not in (None, "") else None,
        "detail_link": sanitize_detail_link(str(detail_link)) if detail_link not in (None, "") else None,
        "decision_date": str(decision_date) if decision_date not in (None, "") else None,
    }



def extract_case_body_text(
    target: str,
    payload: dict[str, Any],
    fallback_text: str | None = None,
) -> str:
    texts: list[str] = []
    response_format = str(payload.get("_response_format") or "").strip().lower()

    if response_format == "html":
        html_text = payload.get("text")
        if html_text not in (None, ""):
            return _normalize_structure(str(html_text))

    texts.extend(_find_all_recursive(payload, TEXT_KEYS_BY_TARGET[target]))
    texts.extend(_find_all_recursive(payload, GENERIC_TEXT_KEYS))

    if not texts:
        texts.extend(list(_walk_strings(payload)))

    if fallback_text not in (None, ""):
        texts.append(str(fallback_text))

    deduped = _dedup_texts(texts)
    return sanitize_inline_urls("\n\n".join(deduped).strip())


def extract_case_body_sections(
    target: str,
    payload: dict[str, Any],
    fallback_text: str | None = None,
) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    seen: set[str] = set()

    for label, keys in BODY_SECTION_KEYS_BY_TARGET.get(target, ()):
        texts = _find_all_recursive(payload, keys)
        deduped = _dedup_texts(texts)
        if not deduped:
            continue
        section_text = sanitize_inline_urls("\n\n".join(deduped).strip())
        normalized = _normalize_space(section_text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        sections.append({"label": label, "text": section_text})

    if not sections and fallback_text not in (None, ""):
        fallback_body = _normalize_structure(str(fallback_text))
        if fallback_body:
            sections.append({"label": "본문", "text": sanitize_inline_urls(fallback_body)})

    return sections



def parse_case_payload(
    target: str,
    payload: dict[str, Any],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fallback = fallback or {}
    meta = extract_case_meta(target, payload, fallback=fallback)
    body_text = extract_case_body_text(target, payload, fallback_text=str(fallback.get("text") or ""))
    body_sections = extract_case_body_sections(target, payload, fallback_text=str(fallback.get("text") or ""))
    structured_case_refs = extract_structured_case_number_refs(
        target,
        payload,
        exclude_numbers=[meta.get("doc_number")],
    )

    return {
        **meta,
        "body_text": body_text,
        "body_sections": body_sections,
        "structured_case_refs": structured_case_refs,
        "source_format": payload.get("_response_format"),
        "source_content_type": payload.get("_response_content_type"),
        "source_url": payload.get("_response_url"),
    }



def find_related_law_names(text: str, family_law_names: list[str]) -> list[str]:
    normalized_text = _normalize_name(text)
    matched: list[str] = []
    seen: set[str] = set()

    for law_name in family_law_names:
        candidate = str(law_name or "").strip()
        if not candidate:
            continue
        normalized_law = _normalize_name(candidate)
        if normalized_law and normalized_law in normalized_text and candidate not in seen:
            seen.add(candidate)
            matched.append(candidate)

    return matched



FIRST_ARTICLE_PATTERN = re.compile(r"^제(\d+)조(?:의(\d+))?")
CONTINUED_ARTICLE_PATTERN = re.compile(r"^(?:,|및|와|과|또는|혹은|·)(?:제)?(\d+)조(?:의(\d+))?")
CASE_NUMBER_REF_PATTERN = re.compile(r"(?<!\d)(?P<year>\d{2,4})(?P<case_type>[가-힣]{1,4})(?P<serial>\d{1,8})(?!\d)")
ALLOWED_CASE_TYPE_TOKENS = {
    "가",
    "가단",
    "가합",
    "가소",
    "거",
    "고",
    "고단",
    "고약",
    "고정",
    "고합",
    "고합부",
    "고정단",
    "과",
    "구",
    "구단",
    "구라",
    "구합",
    "그",
    "기",
    "나",
    "누",
    "다",
    "더",
    "도",
    "두",
    "드",
    "라",
    "마",
    "머",
    "모",
    "무",
    "바",
    "사",
    "서",
    "소",
    "수",
    "스",
    "아",
    "오",
    "우",
    "자",
    "재",
    "저",
    "차",
    "카",
    "타",
    "파",
    "하",
    "허",
    "헌가",
    "헌나",
    "헌다",
    "헌라",
    "헌마",
    "헌바",
    "헌사",
    "헌아",
}
DISALLOWED_CASE_TYPE_TOKENS = {
    "개",
    "건",
    "개월",
    "년",
    "만",
    "명",
    "배",
    "백",
    "번",
    "부",
    "시",
    "억",
    "월",
    "원",
    "일",
    "장",
    "절",
    "점",
    "조",
    "주",
    "쪽",
    "천",
    "층",
    "퍼센트",
    "평",
    "항",
    "호",
    "회",
}
CASE_REF_CONTEXT_PATTERN = re.compile(
    r"(판결|결정|사건|사건번호|선고|재판|대법원|고등법원|지방법원|법원|헌재|헌법재판소|원심|항소심|상고심|참조)"
)
CASE_REF_TRAILING_NOISE_PATTERN = re.compile(r"^(?:원|만원|천원|억원|조원|개|건|명|차|항|호|조)")


def _format_article_ref(main_no: str, branch_no: str | None) -> dict[str, str]:
    article_key = str(int(main_no)) if not branch_no else f"{int(main_no)}-{int(branch_no)}"
    article_display = f"제{int(main_no)}조" if not branch_no else f"제{int(main_no)}조의{int(branch_no)}"
    return {
        "article_key": article_key,
        "article_no_display": article_display,
    }


def _is_valid_case_type_token(case_type: str) -> bool:
    token = str(case_type or "").strip()
    if not token:
        return False
    if token in DISALLOWED_CASE_TYPE_TOKENS:
        return False
    if any(char in DISALLOWED_CASE_TYPE_TOKENS for char in token):
        return False
    return token in ALLOWED_CASE_TYPE_TOKENS


def _has_case_reference_context(text: str, start: int, end: int) -> bool:
    left = text[max(0, start - 16):start]
    right = text[end:min(len(text), end + 16)]
    return bool(CASE_REF_CONTEXT_PATTERN.search(left) or CASE_REF_CONTEXT_PATTERN.search(right))



def extract_explicit_article_refs(text: str, family_law_names: list[str]) -> dict[str, list[dict[str, str]]]:
    normalized_text = _normalize_name(text)
    results: dict[str, list[dict[str, str]]] = {}

    for law_name in family_law_names:
        candidate = str(law_name or "").strip()
        if not candidate:
            continue
        normalized_law = _normalize_name(candidate)
        if not normalized_law:
            continue

        matches: list[dict[str, str]] = []
        seen_keys: set[str] = set()
        start = 0

        while True:
            law_idx = normalized_text.find(normalized_law, start)
            if law_idx < 0:
                break

            cursor = law_idx + len(normalized_law)
            tail = normalized_text[cursor:]
            first_match = FIRST_ARTICLE_PATTERN.match(tail)
            if not first_match:
                start = law_idx + len(normalized_law)
                continue

            main_no, branch_no = first_match.groups()
            article = _format_article_ref(main_no, branch_no)
            if article["article_key"] not in seen_keys:
                seen_keys.add(article["article_key"])
                matches.append(article)

            cursor += first_match.end()
            while True:
                continued_match = CONTINUED_ARTICLE_PATTERN.match(normalized_text[cursor:])
                if not continued_match:
                    break
                main_no, branch_no = continued_match.groups()
                article = _format_article_ref(main_no, branch_no)
                if article["article_key"] not in seen_keys:
                    seen_keys.add(article["article_key"])
                    matches.append(article)
                cursor += continued_match.end()

            start = law_idx + len(normalized_law)

        if matches:
            results[candidate] = matches

    return results



CASE_NUMBER_REF_PATTERN = re.compile(r"(?<!\d)(\d{2,4}[가-힣]{1,4}\d{1,8})(?!\d)")
INVALID_CASE_CODE_TOKENS = (
    "조",
    "조의",
    "항",
    "항의",
    "호",
    "호의",
    "목",
    "목의",
    "편",
    "장",
    "절",
    "관",
    "만",
    "억",
    "천",
    "백",
    "십",
    "원",
)


def _is_valid_case_number_candidate(candidate: str) -> bool:
    match = re.fullmatch(r"(\d{2,4})([가-힣]{1,4})(\d{1,8})", candidate)
    if match is None:
        return False
    code = str(match.group(2) or "").strip()
    if not code:
        return False
    if code in INVALID_CASE_CODE_TOKENS:
        return False
    if any(token in code for token in INVALID_CASE_CODE_TOKENS):
        return False
    return True


def extract_case_number_refs(text: str, exclude_numbers: Iterable[str] | None = None) -> list[str]:
    normalized_text = _normalize_structure(text)
    if not normalized_text:
        return []

    excluded = {
        _normalize_name(str(item))
        for item in (exclude_numbers or [])
        if str(item or "").strip()
    }

    results: list[str] = []
    seen: set[str] = set()

    for match in CASE_NUMBER_REF_PATTERN.finditer(normalized_text):
        candidate = str(match.group(0)).strip()
        if not candidate:
            continue
        if not _is_valid_case_number_candidate(candidate):
            continue
        normalized_candidate = _normalize_name(candidate)
        if normalized_candidate in excluded or normalized_candidate in seen:
            continue
        seen.add(normalized_candidate)
        results.append(candidate)

    return results


def extract_structured_case_number_refs(
    target: str,
    payload: dict[str, Any],
    exclude_numbers: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    keys = CASE_REFERENCE_KEYS_BY_TARGET.get(target, ())
    if not keys:
        return []

    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for text in _find_all_recursive(payload, keys):
        for case_number in extract_case_number_refs(text, exclude_numbers=exclude_numbers):
            normalized_case_number = _normalize_name(case_number)
            if not normalized_case_number or normalized_case_number in seen:
                continue
            seen.add(normalized_case_number)
            results.append(
                {
                    "case_number": case_number,
                    "source": "structured_field",
                    "field_name": keys[0],
                }
            )

    return results


def build_evidence_preview(
    text: str,
    law_name: str | None = None,
    limit: int = 240,
    anchor: str | None = None,
) -> str:
    normalized_text = _normalize_structure(text)
    if not normalized_text:
        return ""

    search_term = str(anchor or law_name or "").strip()
    if not search_term:
        return normalized_text[:limit]

    idx = normalized_text.find(search_term)
    if idx < 0:
        return normalized_text[:limit]

    start = max(0, idx - 40)
    end = min(len(normalized_text), idx + limit)
    return normalized_text[start:end].strip()
