"""
annotation_types — LLM-produced highlight annotations
=======================================================

These models serve dual purpose:

1. **Structured output schema** for LangChain/LangGraph LLM calls
   (via ``llm.with_structured_output(ArticleAnnotations)``)
2. **Input to the HTML exporter** for rendering ``<mark>`` overlays

Highlights use **exact string matching** on ``IRGroup.formatted_str``.
The resolver converts text matches to character offsets internally.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Highlight(BaseModel):
    """A single highlighted span identified by exact text match."""
    text: str = Field(description="하이라이트할 정확한 텍스트 (formatted_str에서 그대로 복사)")
    label: str = Field(default="", description="하이라이트 설명 (예: '문제 조항', '핵심 조건')")
    color: str = Field(default="#FFFF00", description="하이라이트 색상 (CSS hex)")
    occurrence: int = Field(default=1, description="같은 텍스트가 여러 번 나올 경우, 몇 번째를 하이라이트할지 (1부터 시작, 0이면 전부)")


class ResolvedHighlight(BaseModel):
    """A highlight resolved to character offsets. Internal use only."""
    start: int
    end: int
    label: str = ""
    color: str = "#FFFF00"


class ArticleAnnotations(BaseModel):
    """Structured output for an LLM that analyzes and highlights parts of an article.

    Usage with LangChain::

        llm = ChatOpenAI(...)
        highlighter = llm.with_structured_output(ArticleAnnotations, method="json_mode")
        result = highlighter.invoke([("system", prompt), ("user", article.formatted_str)])
    """
    reasoning: str = Field(
        description="분석 근거를 간단히 설명하세요. 이 필드를 먼저 채워넣으세요!"
    )
    highlights: list[Highlight] = Field(
        default_factory=list,
        description="하이라이트할 부분들의 목록"
    )

    def resolve(self, formatted_str: str) -> list[ResolvedHighlight]:
        """Convert text-based highlights to character offsets.

        Matches ``Highlight.text`` against *formatted_str*.  If
        ``occurrence`` is 0, all occurrences are highlighted; otherwise
        only the Nth match (1-based).

        Unmatched highlights are silently skipped.
        """
        resolved: list[ResolvedHighlight] = []
        for h in self.highlights:
            if not h.text:
                continue
            start = 0
            match_num = 0
            while True:
                idx = formatted_str.find(h.text, start)
                if idx == -1:
                    break
                match_num += 1
                if h.occurrence == 0 or match_num == h.occurrence:
                    resolved.append(ResolvedHighlight(
                        start=idx,
                        end=idx + len(h.text),
                        label=h.label,
                        color=h.color,
                    ))
                    if h.occurrence != 0:
                        break
                start = idx + 1
        return resolved
