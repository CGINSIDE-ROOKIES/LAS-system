"""LLM 입력용 컨텍스트 빌딩 모듈.

검색 결과 rows를 LLM 프롬프트에 전달할 수 있는 형태로 변환한다.
"""

from __future__ import annotations

import re

_MIN_BOUNDARY_RATIO = 0.55
_DEFAULT_UNKNOWN_TYPE_ORDER = 9
_TYPE_ORDER = {"law": 0, "expc": 1, "prec": 2, "decc": 3, "detc": 4}


# ── 텍스트 전처리 ─────────────────────────────────────────────────────────────

def clean_content(text: str) -> str:
    """연속 공백·개행을 단일 공백으로 정규화한다.

    retrieval 외 모듈에서도 재사용 가능한 범용 정규화 유틸이다.
    """
    return re.sub(r"\s+", " ", text).strip()


def truncate_on_semantic_boundary(text: str, limit: int) -> str:
    """문장/조문 경계를 우선 보존하며 limit 이내로 자른다.

    - 1순위: 조문 경계 (제N조/제N항/제N호/①②③...)
    - 2순위: 문장 경계 (. ? ! ; : 다.)
    - 3순위: 공백 경계
    """
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text

    window = text[:limit]
    min_boundary_idx = int(limit * _MIN_BOUNDARY_RATIO)

    # 한국 법령 표기(제N조/항/호, ①②③...) + 영문 법령 스타일(Article/Section/Clause/Item)
    article_matches = [
        m.start()
        for m in re.finditer(
            r"(제\s*\d+\s*(조의?\d*|항|호)|[①②③④⑤⑥⑦⑧⑨⑩]|"
            r"\b(?:Article|Section|Clause|Item)\s*\d+\b)",
            window,
            flags=re.IGNORECASE,
        )
    ]
    article_cut = max(article_matches) if article_matches else -1
    if article_cut >= min_boundary_idx:
        return window[:article_cut].strip()

    sent_matches = [m.end() for m in re.finditer(r"(다\.|[.!?;:])\s*", window)]
    sent_cut = max(sent_matches) if sent_matches else -1
    if sent_cut >= min_boundary_idx:
        return window[:sent_cut].strip()

    ws_cut = window.rfind(" ")
    if ws_cut >= min_boundary_idx:
        return window[:ws_cut].strip()

    return window.strip()


def _context_type_sort_key(
    item: tuple[int, dict[str, object]],
) -> tuple[int, int]:
    """컨텍스트 표시 우선순위: law 계열 우선, 같은 타입이면 원래 순서 유지."""
    idx, row = item
    doc_type = str(row.get("doc_type", "") or "")
    return (_TYPE_ORDER.get(doc_type, _DEFAULT_UNKNOWN_TYPE_ORDER), idx)


# ── LLM 컨텍스트 빌딩 ────────────────────────────────────────────────────────

def build_llm_context_rows(
    rows: list[dict[str, object]],
    *,
    max_content_chars: int,
    max_total_chars: int,
) -> list[dict[str, object]]:
    """LLM 입력용 컨텍스트 배열을 빌드한다. 글자 수 제한을 적용한다.

    주의:
    - build_llm_context_text()와 동일한 타입 우선순위(law 우선)를 먼저 적용해
      "선정 순서"와 "표시 순서"의 불일치를 줄인다.
    - max_total_chars 초과 문서는 break하지 않고 skip하여, 뒤의 짧은 문서를
      포함할 기회를 남긴다.
    """
    out: list[dict[str, object]] = []
    total = 0
    ordered_rows = [row for _, row in sorted(enumerate(rows), key=_context_type_sort_key)]
    for row in ordered_rows:
        text = str(row.get("text", "") or "")
        snippet = str(row.get("snippet", "") or "")
        content = clean_content(text or snippet)
        if not content:
            continue
        if max_content_chars > 0:
            content = truncate_on_semantic_boundary(content, max_content_chars)
        # 문서를 중간에서 자르지 않기 위해 초과 문서는 스킵한다.
        # break 대신 continue하여 뒤쪽의 짧은 문서가 들어올 수 있게 한다.
        if max_total_chars > 0 and total + len(content) > max_total_chars:
            continue
        out.append(
            {
                "source_id": str(row.get("source_id", "") or ""),
                "law_name": str(row.get("law_name", "") or ""),
                "doc_type": str(row.get("doc_type", "") or ""),
                "score": row.get("score"),
                "content": content,
            }
        )
        total += len(content)
    return out


def build_llm_context_text(
    question: str,
    contexts: list[dict[str, object]],
    law_context_added: bool,
) -> str:
    """LLM에 바로 전달 가능한 구조화 텍스트를 생성한다.

    LLM이 기준/근거 문서를 빠르게 파악하도록 law 계열을 먼저 제시한다.
    """
    lines: list[str] = [f"[질문]\n{question}", "", "[컨텍스트 메타]"]
    lines.append(f"law_context_added={str(law_context_added).lower()}")
    lines.append(f"context_docs={len(contexts)}")
    lines.append("")
    lines.append("[참고 법령 및 판례]")

    if not law_context_added:
        lines.append(
            "- 주의: 이번 결과에는 요청한 수의 법령(law) 문서가 포함되지 않았습니다."
        )

    if not contexts:
        lines.append("(검색 결과 없음)")
        return "\n".join(lines)

    # LLM 답변 안정성을 위해 law 계열 문서를 먼저 제시한다.
    # build_llm_context_rows()와 같은 우선순위를 공유해 순서 일관성을 유지한다.
    ordered = sorted(enumerate(contexts), key=_context_type_sort_key)

    for i, (_, ctx) in enumerate(ordered, start=1):
        doc_type = str(ctx.get("doc_type", "") or "")
        law_name = str(ctx.get("law_name", "") or "")
        content = str(ctx.get("content", "") or "")
        # source_id는 내부 식별자 성격이 강해 기본 프롬프트에는 노출하지 않는다.
        # law_name은 모델 근거 정렬에 도움을 줄 수 있어 비어있지 않을 때만 짧게 노출한다.
        if law_name:
            lines.append(f"{i}. ({doc_type}) law_name={law_name}")
        else:
            lines.append(f"{i}. ({doc_type})")
        lines.append(content)
        lines.append("")

    return "\n".join(lines).strip()
