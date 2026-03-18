"""LLM 입력용 컨텍스트 빌딩 모듈.

검색 결과 rows를 LLM 프롬프트에 전달할 수 있는 형태로 변환한다.
"""

from __future__ import annotations

import re


# ── 텍스트 전처리 ─────────────────────────────────────────────────────────────

def clean_content(text: str) -> str:
    """연속 공백·개행을 단일 공백으로 정규화한다."""
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

    article_matches = [
        m.start()
        for m in re.finditer(r"(제\s*\d+\s*[조항호]|[①②③④⑤⑥⑦⑧⑨⑩])", window)
    ]
    article_cut = max(article_matches) if article_matches else -1
    if article_cut >= int(limit * 0.55):
        return window[:article_cut].strip()

    sent_matches = [m.end() for m in re.finditer(r"(다\.|[.!?;:])\s*", window)]
    sent_cut = max(sent_matches) if sent_matches else -1
    if sent_cut >= int(limit * 0.55):
        return window[:sent_cut].strip()

    ws_cut = window.rfind(" ")
    if ws_cut >= int(limit * 0.55):
        return window[:ws_cut].strip()

    return window.strip()


# ── LLM 컨텍스트 빌딩 ────────────────────────────────────────────────────────

def build_llm_context_rows(
    rows: list[dict[str, object]],
    *,
    max_content_chars: int,
    max_total_chars: int,
) -> list[dict[str, object]]:
    """LLM 입력용 컨텍스트 배열을 빌드한다. 글자 수 제한을 적용한다."""
    out: list[dict[str, object]] = []
    total = 0
    for row in rows:
        text = str(row.get("text", "") or "")
        snippet = str(row.get("snippet", "") or "")
        content = clean_content(text or snippet)
        if not content:
            continue
        if max_content_chars > 0:
            content = truncate_on_semantic_boundary(content, max_content_chars)
        # 마지막 문서를 중간에서 자르지 않기 위해, 전체 한도 초과 시 해당 문서는 스킵하고 종료.
        if max_total_chars > 0 and total + len(content) > max_total_chars:
            break
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
    lines: list[str] = [f"[질문]\n{question}", "", "[메타]"]
    lines.append(f"- law_context_added: {str(law_context_added).lower()}")
    lines.append(f"- context_docs: {len(contexts)}")
    lines.append("")
    lines.append("[참고 법령 및 판례]")

    if not law_context_added:
        lines.append(
            "- 주의: 이번 결과에는 요청한 수의 법령(law) 문서가 포함되지 않았습니다."
        )

    if not contexts:
        lines.append("(검색 결과 없음)")
        return "\n".join(lines)

    # LLM 답변 안정성을 위해 law 계열 문서를 먼저 제시.
    type_order = {"law": 0, "expc": 1, "prec": 2, "decc": 3, "detc": 4}
    ordered = sorted(
        enumerate(contexts),
        key=lambda item: (
            type_order.get(str(item[1].get("doc_type", "") or ""), 9),
            item[0],
        ),
    )

    for i, (_, ctx) in enumerate(ordered, start=1):
        source_id = str(ctx.get("source_id", "") or "")
        doc_type = str(ctx.get("doc_type", "") or "")
        law_name = str(ctx.get("law_name", "") or "")
        content = str(ctx.get("content", "") or "")
        law_name_disp = law_name if law_name else "-"
        lines.append(
            f"{i}. ({doc_type}) law_name={law_name_disp} | source_id={source_id}"
        )
        lines.append(content)
        lines.append("")

    return "\n".join(lines).strip()
