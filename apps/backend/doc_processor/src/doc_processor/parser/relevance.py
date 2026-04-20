from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from document_processor import DocIR

from ..prompts import load_prompt
from ..state import ParserConfig
from ..parser_types import RelevanceDecision, RelevanceMode, WorkflowMeta
from .llm_utils import invoke_structured_model
from .selectors import build_paragraph_analyses, non_empty_paragraphs
from .rules import match_clause_start

POSITIVE_KEYWORDS = (
    "계약서",
    "합의서",
    "부속합의서",
    "전속계약서",
    "양도계약서",
    "설정계약서",
    "근로계약",
    "표준계약서",
)

NEGATIVE_KEYWORDS = (
    "공고",
    "안내",
    "매뉴얼",
    "신청방법",
    "사업설명",
    "사업개요",
    "시행계획",
    "모집",
)


class RelevanceLLMOutput(BaseModel):
    is_relevant: bool
    doc_kind: Literal["contract", "non_contract", "uncertain"]
    reason: str
    confidence: float | None = None


def score_relevance(doc: DocIR, config: ParserConfig) -> RelevanceDecision:
    paragraphs = non_empty_paragraphs(build_paragraph_analyses(doc))
    preview = paragraphs[: config.relevance_preview_paragraphs]
    preview_texts = [paragraph.text for paragraph in preview]
    positives: list[str] = []
    negatives: list[str] = []
    score = 0

    title = preview_texts[0] if preview_texts else ""
    for keyword in POSITIVE_KEYWORDS:
        if any(keyword in text for text in preview_texts[:8]):
            positives.append(keyword)
            score += 2 if keyword in title else 1
    for keyword in NEGATIVE_KEYWORDS:
        if any(keyword in text for text in preview_texts[:8]):
            negatives.append(keyword)
            score -= 2 if keyword in title else 1

    early_clause_hits = 0
    for text in preview_texts[:15]:
        if match_clause_start(text, rule_name="article"):
            early_clause_hits += 1
    if early_clause_hits >= 2:
        positives.append("early_article_numbering")
        score += 3
    elif early_clause_hits == 1:
        positives.append("single_article_numbering")
        score += 1

    if any(text.strip().startswith("1.") for text in preview_texts[:12]):
        positives.append("numeric_headings")
        score += 1

    is_relevant = score > 0
    reason = f"Keyword score={score}; positives={positives or ['none']}; negatives={negatives or ['none']}."
    return RelevanceDecision(
        mode=config.relevance_mode,
        is_relevant=is_relevant,
        score=score,
        reason=reason,
        positives=positives,
        negatives=negatives,
        doc_kind="contract" if is_relevant else "non_contract",
    )


def needs_llm_relevance_review(decision: RelevanceDecision, config: ParserConfig) -> bool:
    if config.relevance_mode != RelevanceMode.KEYWORD_THEN_LLM:
        return False
    return abs(decision.score) <= config.relevance_ambiguity_threshold


def review_relevance_with_llm(
    doc: DocIR,
    config: ParserConfig,
    *,
    keyword_decision: RelevanceDecision,
) -> RelevanceDecision:
    paragraphs = non_empty_paragraphs(build_paragraph_analyses(doc))
    preview = paragraphs[: config.relevance_preview_paragraphs]
    payload = {
        "source_path": doc.source_path,
        "source_doc_type": doc.source_doc_type,
        "title": preview[0].text if preview else "",
        "paragraphs": [
            {"unit_id": paragraph.unit_id, "page_number": paragraph.page_number, "text": paragraph.text}
            for paragraph in preview
        ],
        "keyword_decision": keyword_decision.model_dump(mode="json"),
    }
    prompt = load_prompt("parser/relevance_screening", profile=config.prompt_profile)
    output = invoke_structured_model(
        profile=config.relevance_llm_profile,
        prompt=prompt,
        payload=payload,
        schema=RelevanceLLMOutput,
        model_override=config.relevance_model_override,
        config=config,
    )
    return RelevanceDecision(
        mode=config.relevance_mode,
        is_relevant=output.is_relevant,
        score=keyword_decision.score,
        reason=output.reason,
        positives=keyword_decision.positives,
        negatives=keyword_decision.negatives,
        llm_used=True,
        doc_kind="contract" if output.doc_kind == "contract" else "non_contract",
    )
