"""
Risk analysis worker — per-article risk analysis with optional RAG.

Used as a Send() target in the review pipeline. Each worker:
1. Calls risk_llm to analyze the article for legal risks
2. If any risk needs legal verification, calls search_law() from vector_db
3. Re-analyzes with search context if search was performed
4. Programmatically converts risks → ArticleAnnotations (highlights)
"""

from pydantic import ValidationError
from langchain_core.exceptions import OutputParserException

from doc_processor.llms import midm as llm
from doc_processor.prompts import get_prompts
from doc_processor.core.vector_db import search_law
from doc_processor.las_types import (
    ArticleAnnotations, Highlight,
    RiskAnalysisResult, ArticleRiskReport, ArticleAnalysisState,
)

prompts = get_prompts()

###################################################################################################
# LLM INSTANCES
###################################################################################################

risk_llm = llm.with_structured_output(RiskAnalysisResult, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError, OutputParserException), stop_after_attempt=3)

risk_context_llm = llm.with_structured_output(RiskAnalysisResult, method="json_mode") \
    .with_retry(retry_if_exception_type=(ValidationError, ValueError, OutputParserException), stop_after_attempt=3)

###################################################################################################
# HELPERS
###################################################################################################

_SEVERITY_COLORS = {
    "high": "#FF6B6B",
    "medium": "#FFA500",
    "low": "#FFFF00",
}

# Conservative estimate: 2.5 chars per token for Korean text
_MAX_ARTICLE_CHARS = 3500  # ~1400 tokens, leaving room for prompt + response in 4K


def _truncate_article(text: str, max_chars: int = _MAX_ARTICLE_CHARS) -> str:
    """Truncate long articles, keeping start and end for context."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n[...중략...]\n\n" + text[-half:]


def _risks_to_annotations(result: RiskAnalysisResult) -> ArticleAnnotations:
    """Convert RiskAnalysisResult → ArticleAnnotations programmatically."""
    highlights = []
    for risk in result.risks:
        if not risk.clause_text:
            continue
        label_parts = [f"[{risk.severity.upper()}] {risk.risk_type}"]
        if risk.explanation:
            label_parts.append(risk.explanation)
        if risk.legal_basis:
            label_parts.append(f"근거: {risk.legal_basis}")

        highlights.append(Highlight(
            text=risk.clause_text,
            label=" | ".join(label_parts),
            color=_SEVERITY_COLORS.get(risk.severity, "#FFFF00"),
        ))

    return ArticleAnnotations(
        reasoning=result.reasoning,
        highlights=highlights,
    )

###################################################################################################
# WORKER NODE
###################################################################################################

def risk_analysis_worker(state: ArticleAnalysisState):
    """Per-article risk analysis worker, used as a Send() target.

    Returns dict with ``analysis_temp`` for the reducer to collect.
    """
    group_idx = state.group_idx
    article_text = state.ir_group.formatted_str
    article_n = state.ir_group.article_n

    # Skip empty articles
    if not article_text.strip():
        print(f"\n--- RISK SKIP (group {group_idx}, empty)")
        empty_report = ArticleRiskReport(group_idx=group_idx, article_n=article_n)
        empty_annot = ArticleAnnotations(reasoning="빈 조문", highlights=[])
        return {"analysis_temp": [(group_idx, empty_report, empty_annot)]}

    truncated_text = _truncate_article(article_text)

    # --- Call 1: Initial risk analysis ---
    messages = [
        ("system", prompts["risk_analysis"]),
        ("user", truncated_text),
    ]
    print(f"\n--- RISK ANALYSIS TX (group {group_idx}, article {article_n}) ---")
    result = RiskAnalysisResult.model_validate(risk_llm.invoke(messages))
    
    print(f"\n--- RISK ANALYSIS RX (group {group_idx}, article {article_n}) ---")
    print(f"  article: {truncated_text}")
    print(f"  reasoning: {result.reasoning}")
    print(f"  risks found: {len(result.risks)}")
    for r in result.risks:
        print(f"    [{r.severity}] {r.risk_type}: {r.explanation[:60]}...")

    # --- Optional: search for legal basis ---
    search_results_text = ""
    risks_needing_search = [r for r in result.risks if r.needs_search and r.search_query]

    if risks_needing_search:
        # Combine search queries (deduplicate)
        queries = list(dict.fromkeys(r.search_query for r in risks_needing_search))
        all_results = []
        for query in queries[:3]:  # max 3 searches per article
            print(f"\n--- SEARCH (group {group_idx}): '{query}' ---")
            res = search_law(query, k=3, max_chars=900)
            all_results.append(res)
        search_results_text = "\n\n===\n\n".join(all_results)

        # --- Call 2: Re-analyze with context ---
        # Truncate more aggressively to fit article + search results
        short_text = _truncate_article(article_text, max_chars=2000)
        context_messages = [
            ("system", prompts["risk_analysis_context"]),
            ("user", f"[계약 조문]\n{short_text}\n\n[관련 법령 검색 결과]\n{search_results_text}"),
        ]
        print(f"\n--- RISK RE-ANALYSIS WITH CONTEXT (group {group_idx}) ---")
        result = RiskAnalysisResult.model_validate(risk_context_llm.invoke(context_messages))
        print(f"  reasoning: {result.reasoning}")
        print(f"  risks found: {len(result.risks)}")
        for r in result.risks:
            basis = f" | 근거: {r.legal_basis}" if r.legal_basis else ""
            print(f"    [{r.severity}] {r.risk_type}: {r.explanation[:60]}{basis}")

    # --- Build outputs ---
    report = ArticleRiskReport(
        group_idx=group_idx,
        article_n=article_n,
        risks=result.risks,
        referenced_laws=search_results_text,
    )
    annotation = _risks_to_annotations(result)

    return {"analysis_temp": [(group_idx, report, annotation)]}
