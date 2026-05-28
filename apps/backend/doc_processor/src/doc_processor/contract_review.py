from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import difflib
import hashlib
import json
import logging
import operator
import os
import re
import time
from typing import Annotated, Any, Literal, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt
from pydantic import BaseModel, Field, ValidationError, model_validator

from .api import parse_document, render_review_html
from .api_types import (
    ClauseSummary,
    DocumentInput,
    ParagraphPreview,
    ParseDocumentResult,
    TextAnnotation,
    TextEdit,
)
from .env import ensure_local_env_loaded
from .parser_types import ParagraphCategory, RelevanceMode

logger = logging.getLogger(__name__)

RiskLevel = Literal["none", "low", "mid", "high", "crit"]
SuggestionStatus = Literal["pending", "accepted", "rejected", "feedback"]
HitlRequestKind = Literal["suggested_edit", "human_input"]
HitlDecisionAction = Literal["accept", "reject", "feedback", "provide_info", "manual_edit"]

_RISK_LEVELS: tuple[RiskLevel, ...] = ("none", "low", "mid", "high", "crit")
_RISK_ORDER: dict[RiskLevel, int] = {level: index for index, level in enumerate(_RISK_LEVELS)}
_RISK_LABELS: dict[RiskLevel, str] = {
    "none": "None",
    "low": "low",
    "mid": "mid",
    "high": "high",
    "crit": "crit",
}
_RISK_COLORS: dict[RiskLevel, str] = {
    "none": "#E5E7EB",
    "low": "#D9F99D",
    "mid": "#FEF08A",
    "high": "#FDBA74",
    "crit": "#FCA5A5",
}
_RISK_LEVEL_ALIASES: dict[str, RiskLevel] = {
    "": "mid",
    "none": "none",
    "no": "none",
    "no_risk": "none",
    "no risk": "none",
    "ok": "none",
    "info": "none",
    "low": "low",
    "minor": "low",
    "mid": "mid",
    "medium": "mid",
    "med": "mid",
    "moderate": "mid",
    "high": "high",
    "critical": "crit",
    "crit": "crit",
    "severe": "crit",
}

_CONTRACT_REVIEW_SYSTEM_PROMPT = """You are a legal contract review assistant.
Review one contract clause at a time using only the supplied legal RAG evidence.
Return strict JSON only. Do not include markdown, prose, or unsupported claims.
If the evidence does not show a concrete legal or drafting risk, return {"findings":[]}.
The target users are Korean legal/business users. Write every user-facing response in Korean:
title, rationale, recommendation, replacement_text, full_replacement_text, and human_question.
Keep source_ids, node ids, and machine labels unchanged.
Assign risk_level with this rubric:
- none: no concrete source-backed issue. Do not emit findings just to say none.
- low: minor drafting ambiguity, missing detail, or negotiability concern with limited legal exposure.
- mid: meaningful ambiguity, enforceability concern, statutory compliance risk, or operational burden that needs legal review.
- high: likely illegal, unfair, unenforceable, or creates significant monetary/rights exposure if accepted as written.
- crit: severe statutory conflict, immediate invalidity risk, criminal/regulatory exposure, or large non-recoverable loss.
Each finding must cite source_ids from the evidence and must preserve human control:
recommend edits, but do not imply they should be applied without user approval."""


class RagEvidenceClient(Protocol):
    def query_legal_db(
        self,
        query: str,
        *,
        doc_types: list[str] | None = None,
        law_names: list[str] | None = None,
        intent: str | None = None,
        search_query: str | None = None,
        hypothetical_doc: str | None = None,
        top_k: int | None = None,
    ) -> Mapping[str, Any]:
        ...


class ReviewGenerationClient(Protocol):
    def generate(self, prompt: str, *, system_prompt: str | None = None) -> Any:
        ...


class ContractReviewConfig(BaseModel):
    top_k: int = Field(default=8, ge=1, le=50)
    max_clauses: int | None = Field(default=None, ge=1)
    max_clause_chars: int = Field(default=4000, ge=500)
    max_source_text_chars: int = Field(default=1200, ge=100)
    max_sources_per_finding: int = Field(default=3, ge=1)
    max_concurrent_risk_reviews: int = Field(default=8, ge=1, le=32)
    max_generation_repair_attempts: int = Field(default=3, ge=1, le=5)
    max_generation_provider_retry_attempts: int = Field(default=3, ge=1, le=8)
    generation_provider_retry_base_delay_sec: float = Field(default=1.0, ge=0.0, le=60.0)
    doc_types: list[str] | None = Field(default_factory=lambda: ["law", "prec", "detc", "decc", "expc"])
    law_names: list[str] | None = None
    include_review_html: bool = True
    review_title: str = "계약 리스크 검토"
    pause_for_hitl: bool = False
    hitl_min_risk_level: RiskLevel = "low"


class ContractReviewEnvStatus(BaseModel):
    ready: bool
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    qdrant_url_configured: bool = False
    qdrant_collections: list[str] = Field(default_factory=list)
    opensearch_url_configured: bool = False
    opensearch_indices: list[str] = Field(default_factory=list)
    embedding_model: str = ""
    embedding_dimensions: int | None = None
    llm_provider: str = ""
    llm_model: str = ""


@dataclass(frozen=True)
class ContractReviewClients:
    rag_client: RagEvidenceClient
    generation_client: ReviewGenerationClient
    env_status: ContractReviewEnvStatus


class ReviewContractRequest(BaseModel):
    document: DocumentInput | None = None
    source_path: str | None = None
    relevance_mode: RelevanceMode = RelevanceMode.KEYWORD_THEN_LLM
    boundary_review_enabled: bool = True
    label_review_enabled: bool = True
    parser_max_concurrent_workers: int = Field(default=4, ge=1, le=32)
    parser_llm_repair_max_attempts: int = Field(default=3, ge=1, le=5)
    prompt_profile: str = "default"
    config: ContractReviewConfig = Field(default_factory=ContractReviewConfig)

    @model_validator(mode="after")
    def _validate_source(self) -> "ReviewContractRequest":
        if self.document is not None and self.source_path is not None:
            raise ValueError("Specify either document or source_path, not both.")
        if self.document is None and self.source_path is None:
            raise ValueError("Provide either document or source_path.")
        return self


class ContractReviewSource(BaseModel):
    rank: int | None = None
    source_id: str
    doc_type: str = ""
    law_name: str = ""
    article_no: str = ""
    citation: str = ""
    snippet: str = ""
    text: str = ""
    score: int | float | str | None = None


class _GeneratedReviewFinding(BaseModel):
    risk_level: str = "mid"
    issue_type: str = "contract_risk"
    title: str = ""
    target_node_id: str = ""
    selected_text: str = ""
    problematic_text: str = ""
    rationale: str = ""
    recommendation: str = ""
    replacement_text: str = ""
    full_replacement_text: str = ""
    human_question: str = ""
    source_ids: list[str] = Field(default_factory=list)


class _GeneratedReviewPayload(BaseModel):
    findings: list[_GeneratedReviewFinding] = Field(default_factory=list)


@dataclass(frozen=True)
class _ReviewGenerationAttempt:
    attempt_no: int
    answer: str
    payload: Mapping[str, Any]
    parse_warning: str | None
    validation_issues: list[str]
    findings: list[ContractReviewFinding]


class ContractReviewHumanRequest(BaseModel):
    request_id: str
    finding_id: str
    clause_id: str
    clause_no: str | None = None
    risk_level: RiskLevel
    title: str
    kind: HitlRequestKind
    prompt: str
    guidance: str = ""
    selected_text: str = ""
    proposed_edit: TextEdit | None = None
    diff: str | None = None
    source_citations: list[str] = Field(default_factory=list)
    allowed_actions: list[HitlDecisionAction] = Field(default_factory=list)


class ContractReviewHumanDecision(BaseModel):
    finding_id: str
    action: HitlDecisionAction
    comment: str = ""
    provided_info: str = ""
    manual_text: str = ""


class ContractReviewFinding(BaseModel):
    finding_id: str
    clause_id: str
    clause_no: str | None = None
    target_node_ids: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "mid"
    issue_type: str = "contract_risk"
    title: str
    problematic_text: str = ""
    rationale: str
    recommendation: str
    human_question: str = ""
    sources: list[ContractReviewSource] = Field(default_factory=list)
    annotation: TextAnnotation | None = None
    proposed_edit: TextEdit | None = None
    human_request: ContractReviewHumanRequest | None = None
    status: SuggestionStatus = "pending"


class ClauseReviewResult(BaseModel):
    clause_id: str
    clause_no: str | None = None
    title: str | None = None
    target_node_ids: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "none"
    query: str
    law_context_status: str = ""
    source_count: int = 0
    findings: list[ContractReviewFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContractEditRiskValidationResult(BaseModel):
    ok: bool
    risk_level: RiskLevel = "none"
    failure_threshold: RiskLevel = "mid"
    target_node_id: str
    clause_id: str | None = None
    clause_no: str | None = None
    reason: str = ""
    query: str = ""
    source_count: int = 0
    findings: list[ContractReviewFinding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContractReviewResult(BaseModel):
    parse_result: ParseDocumentResult
    clause_reviews: list[ClauseReviewResult] = Field(default_factory=list)
    findings: list[ContractReviewFinding] = Field(default_factory=list)
    risk_level: RiskLevel = "none"
    clause_risk_counts: dict[RiskLevel, int] = Field(
        default_factory=lambda: {level: 0 for level in _RISK_LEVELS}
    )
    review_html: str | None = None
    hitl_requests: list[ContractReviewHumanRequest] = Field(default_factory=list)
    human_decisions: list[ContractReviewHumanDecision] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClauseReviewWorkItem(BaseModel):
    index: int
    clause: ClauseSummary
    paragraphs: list[ParagraphPreview] = Field(default_factory=list)
    clause_text: str = ""
    query: str = ""


class ContractReviewGraphState(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    request: ReviewContractRequest | None = None
    parse_result: ParseDocumentResult | None = None
    config: ContractReviewConfig = Field(default_factory=ContractReviewConfig)
    render_document: DocumentInput | None = None
    render_source_path: str | None = None
    rag_client: Any | None = Field(default=None, exclude=True)
    generation_client: Any | None = Field(default=None, exclude=True)
    review_units: list[ClauseReviewWorkItem] = Field(default_factory=list)
    active_review_unit: ClauseReviewWorkItem | None = None
    risk_review_results: Annotated[list[dict[str, Any]], operator.add] = Field(default_factory=list)
    clause_reviews: list[ClauseReviewResult] = Field(default_factory=list)
    findings: list[ContractReviewFinding] = Field(default_factory=list)
    hitl_requests: list[ContractReviewHumanRequest] = Field(default_factory=list)
    human_decisions: list[ContractReviewHumanDecision] = Field(default_factory=list)
    result: ContractReviewResult | None = None
    warnings: list[str] = Field(default_factory=list)


def check_contract_review_env() -> ContractReviewEnvStatus:
    ensure_local_env_loaded()

    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    qdrant_collections = _split_env_list("QDRANT_COLLECTIONS")
    opensearch_url = os.getenv("OPENSEARCH_URL", "").strip()
    opensearch_indices = _split_env_list("OPENSEARCH_INDEX")
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large").strip()
    missing: list[str] = []
    warnings: list[str] = []
    embedding_dimensions = _parse_optional_int_env("EMBEDDING_DIMENSIONS", warnings)
    if embedding_dimensions is None:
        warnings.append(
            "EMBEDDING_DIMENSIONS is not set; set it to 1024 for the current reduced-dimension Qdrant DB."
        )

    if not qdrant_url:
        missing.append("QDRANT_URL")
    if not qdrant_collections:
        missing.append("QDRANT_COLLECTIONS")
    if not os.getenv("EMBEDDING_API_KEY", "").strip():
        missing.append("EMBEDDING_API_KEY")

    if opensearch_url and not opensearch_indices:
        warnings.append("OPENSEARCH_URL is set but OPENSEARCH_INDEX is empty; BM25 retrieval may be skipped.")
    if opensearch_indices and not opensearch_url:
        warnings.append("OPENSEARCH_INDEX is set but OPENSEARCH_URL is empty; BM25 retrieval is disabled.")

    if provider == "gemini":
        model = os.getenv("LLM_MODEL", "").strip()
        if not model:
            missing.append("LLM_MODEL")
        if not os.getenv("LLM_API_KEY", "").strip():
            missing.append("LLM_API_KEY")
    elif provider == "openai_compat":
        model = os.getenv("LLM_MODEL", "").strip()
        if not model:
            missing.append("LLM_MODEL")
        if not (
            os.getenv("LLM_URL", "").strip()
            or os.getenv("LLM_BASE_URL", "").strip()
        ):
            missing.append("LLM_URL or LLM_BASE_URL")
        if not os.getenv("LLM_API_KEY", "").strip():
            missing.append("LLM_API_KEY")
    else:
        model = os.getenv("LLM_MODEL", "").strip()
        missing.append("LLM_PROVIDER=openai_compat|gemini")

    return ContractReviewEnvStatus(
        ready=not missing,
        missing=missing,
        warnings=warnings,
        qdrant_url_configured=bool(qdrant_url),
        qdrant_collections=qdrant_collections,
        opensearch_url_configured=bool(opensearch_url),
        opensearch_indices=opensearch_indices,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        llm_provider=provider,
        llm_model=model,
    )


def build_contract_review_clients_from_env() -> ContractReviewClients:
    status = check_contract_review_env()
    if not status.ready:
        missing = ", ".join(status.missing)
        raise RuntimeError(f"Contract review RAG env is incomplete: {missing}")

    from rag_pipeline.generation import GenerationService, RagPipeline

    return ContractReviewClients(
        rag_client=RagPipeline.from_env(),
        generation_client=GenerationService.from_env(),
        env_status=status,
    )


def review_contract_document_from_env(request: ReviewContractRequest) -> ContractReviewResult:
    clients = build_contract_review_clients_from_env()
    return review_contract_document(
        request,
        rag_client=clients.rag_client,
        generation_client=clients.generation_client,
    )


def review_contract_document(
    request: ReviewContractRequest,
    *,
    rag_client: RagEvidenceClient,
    generation_client: ReviewGenerationClient,
) -> ContractReviewResult:
    return _invoke_contract_review_graph(
        ContractReviewGraphState(
            request=request,
            config=request.config,
            rag_client=rag_client,
            generation_client=generation_client,
        )
    )


def review_parsed_contract(
    parse_result: ParseDocumentResult,
    *,
    rag_client: RagEvidenceClient,
    generation_client: ReviewGenerationClient,
    config: ContractReviewConfig | None = None,
    render_document: DocumentInput | None = None,
    render_source_path: str | None = None,
) -> ContractReviewResult:
    cfg = config or ContractReviewConfig()
    return _invoke_contract_review_graph(
        ContractReviewGraphState(
            parse_result=parse_result,
            config=cfg,
            render_document=render_document,
            render_source_path=render_source_path,
            rag_client=rag_client,
            generation_client=generation_client,
        )
    )


def validate_contract_edit_risk(
    parse_result: ParseDocumentResult,
    *,
    target_node_id: str,
    candidate_text: str,
    rag_client: RagEvidenceClient,
    generation_client: ReviewGenerationClient,
    config: ContractReviewConfig | None = None,
    failure_threshold: RiskLevel = "mid",
) -> ContractEditRiskValidationResult:
    cfg = (config or ContractReviewConfig()).model_copy(
        update={"include_review_html": False, "pause_for_hitl": False}
    )
    target_node_id = target_node_id.strip()
    candidate_text = candidate_text.strip()
    if not target_node_id:
        raise ValueError("target_node_id is required for edit risk validation.")
    if not candidate_text:
        raise ValueError("candidate_text is required for edit risk validation.")

    clause, paragraphs = _candidate_validation_clause(parse_result, target_node_id, candidate_text)
    clause_text = _clause_text(clause, paragraphs, cfg.max_clause_chars)
    unit = ClauseReviewWorkItem(
        index=0,
        clause=clause,
        paragraphs=list(paragraphs),
        clause_text=clause_text,
        query=_build_rag_query(clause, clause_text),
    )
    review = _review_single_clause_unit(
        unit,
        rag_client=rag_client,
        generation_client=generation_client,
        cfg=cfg,
    )
    threshold = _normalize_risk_level(failure_threshold)
    risk_level = _normalize_risk_level(review.risk_level)
    ok = _RISK_ORDER[risk_level] < _RISK_ORDER[threshold]
    return ContractEditRiskValidationResult(
        ok=ok,
        risk_level=risk_level,
        failure_threshold=threshold,
        target_node_id=target_node_id,
        clause_id=review.clause_id,
        clause_no=review.clause_no,
        reason="" if ok else _edit_validation_failure_reason(review),
        query=review.query,
        source_count=review.source_count,
        findings=review.findings,
        warnings=review.warnings,
    )


def build_contract_review_graph(*, checkpointer: Any | None = None):
    builder = StateGraph(ContractReviewGraphState)
    builder.add_node("load_and_categorize", load_and_categorize_contract)
    builder.add_node("prepare_risk_reviews", prepare_contract_risk_reviews)
    builder.add_node("risk_review_worker", contract_risk_review_worker)
    builder.add_node("finalize_contract_review", finalize_contract_review)
    builder.add_node("human_review", human_review_contract_findings)

    builder.add_edge(START, "load_and_categorize")
    builder.add_edge("risk_review_worker", "finalize_contract_review")
    builder.add_edge("human_review", END)
    if checkpointer is None:
        return builder.compile()
    return builder.compile(checkpointer=checkpointer)


def _invoke_contract_review_graph(initial: ContractReviewGraphState) -> ContractReviewResult:
    graph = build_contract_review_graph()
    rag_client = initial.rag_client
    generation_client = initial.generation_client
    graph_state = initial.model_copy(update={"rag_client": None, "generation_client": None})
    result = graph.invoke(
        graph_state,
        config={
            "max_concurrency": initial.config.max_concurrent_risk_reviews,
            "configurable": {
                "rag_client": rag_client,
                "generation_client": generation_client,
            },
        },
    )
    state = ContractReviewGraphState.model_validate(result)
    if state.result is None:
        raise ValueError("Contract review graph did not produce a result.")
    return state.result


def _coerce_review_state(state: ContractReviewGraphState | dict[str, Any]) -> ContractReviewGraphState:
    return state if isinstance(state, ContractReviewGraphState) else ContractReviewGraphState.model_validate(state)


def _runtime_config_value(config: Any, key: str) -> Any:
    if not isinstance(config, Mapping):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        return None
    return configurable.get(key)


def _checkpoint_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_checkpoint_value(item) for item in value]
    if isinstance(value, tuple):
        return [_checkpoint_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _checkpoint_value(item) for key, item in value.items()}
    return value


def _checkpoint_document_input(document: DocumentInput | None) -> Any:
    if document is None:
        return None
    if getattr(document, "doc_ir", None) is not None:
        return document
    return _checkpoint_value(document)


def load_and_categorize_contract(state: ContractReviewGraphState) -> Command[str]:
    state = _coerce_review_state(state)
    if state.parse_result is not None:
        return Command(goto="prepare_risk_reviews")
    if state.request is None:
        raise ValueError("ContractReviewGraphState.request or parse_result is required.")

    request = state.request
    parse_result = parse_document(
        document=request.document,
        source_path=request.source_path,
        relevance_mode=request.relevance_mode,
        boundary_review_enabled=request.boundary_review_enabled,
        label_review_enabled=request.label_review_enabled,
        max_concurrent_workers=request.parser_max_concurrent_workers,
        llm_repair_max_attempts=request.parser_llm_repair_max_attempts,
        prompt_profile=request.prompt_profile,
        include_paragraphs=True,
        include_clauses=True,
        include_editable_targets=False,
        max_paragraphs=None,
        paragraph_excerpt_length=None,
    )
    return Command(
        update={
            "parse_result": _checkpoint_value(parse_result),
            "config": _checkpoint_value(request.config),
            "render_document": _checkpoint_document_input(request.document),
            "render_source_path": request.source_path,
        },
        goto="prepare_risk_reviews",
    )


def prepare_contract_risk_reviews(state: ContractReviewGraphState) -> Command[str | Send]:
    state = _coerce_review_state(state)
    if state.parse_result is None:
        raise ValueError("parse_result is required before risk review preparation.")
    paragraph_by_id = {paragraph.node_id: paragraph for paragraph in state.parse_result.paragraphs}
    review_units = [
        ClauseReviewWorkItem(
            index=index,
            clause=clause,
            paragraphs=list(paragraphs),
            clause_text=_clause_text(clause, paragraphs, state.config.max_clause_chars),
        )
        for index, (clause, paragraphs) in enumerate(
            _review_clause_units(state.parse_result, paragraph_by_id, state.config)
        )
    ]
    review_units = [
        unit.model_copy(update={"query": _build_rag_query(unit.clause, unit.clause_text)})
        if unit.clause_text.strip()
        else unit
        for unit in review_units
    ]
    if not review_units:
        return Command(update={"review_units": []}, goto="finalize_contract_review")
    return Command(
        update={"review_units": _checkpoint_value(review_units), "risk_review_results": []},
        goto=[
            Send(
                "risk_review_worker",
                {
                    "config": _checkpoint_value(state.config),
                    "active_review_unit": _checkpoint_value(unit),
                },
            )
            for unit in review_units
        ],
    )


def contract_risk_review_worker(state: ContractReviewGraphState, config: RunnableConfig) -> Command[str]:
    state = _coerce_review_state(state)
    if state.active_review_unit is None:
        raise ValueError("active_review_unit is required for risk review worker.")
    rag_client = state.rag_client or _runtime_config_value(config, "rag_client")
    generation_client = state.generation_client or _runtime_config_value(config, "generation_client")
    if rag_client is None:
        raise ValueError("rag_client is required for risk review worker.")
    if generation_client is None:
        raise ValueError("generation_client is required for risk review worker.")

    clause_review = _review_single_clause_unit(
        state.active_review_unit,
        rag_client=rag_client,
        generation_client=generation_client,
        cfg=state.config,
    )
    return Command(
        update={
            "risk_review_results": [
                {
                    "index": state.active_review_unit.index,
                    "review": _checkpoint_value(clause_review),
                }
            ]
        }
    )


def finalize_contract_review(state: ContractReviewGraphState) -> Command[str]:
    state = _coerce_review_state(state)
    if state.parse_result is None:
        raise ValueError("parse_result is required before contract review finalization.")

    reviews_by_index = {
        int(item["index"]): ClauseReviewResult.model_validate(item["review"])
        for item in state.risk_review_results
        if isinstance(item, Mapping) and "index" in item and "review" in item
    }
    clause_reviews = [reviews_by_index[unit.index] for unit in state.review_units if unit.index in reviews_by_index]
    missing_reviews = [
        unit
        for unit in state.review_units
        if unit.index not in reviews_by_index
    ]
    for unit in missing_reviews:
        clause_reviews.append(
            ClauseReviewResult(
                clause_id=unit.clause.clause_id,
                clause_no=unit.clause.clause_no,
                title=unit.clause.title,
                target_node_ids=unit.clause.member_node_ids,
                query=unit.query,
                warnings=["Risk review worker did not return a result."],
            )
        )
    findings = [finding for review in clause_reviews for finding in review.findings]
    hitl_requests = _build_hitl_requests(findings, state.config)
    findings = _attach_human_requests(findings, hitl_requests)
    clause_reviews = _replace_clause_review_findings(clause_reviews, findings)
    warnings = [
        warning
        for review in clause_reviews
        for warning in review.warnings
    ]
    clause_risk_counts = _clause_risk_counts(clause_reviews)
    review_html = _render_findings_html(
        findings,
        cfg=state.config,
        render_document=state.render_document,
        render_source_path=state.render_source_path,
        warnings=warnings,
    )
    result = ContractReviewResult(
        parse_result=state.parse_result,
        clause_reviews=clause_reviews,
        findings=findings,
        risk_level=_max_risk_level(review.risk_level for review in clause_reviews),
        clause_risk_counts=clause_risk_counts,
        review_html=review_html,
        hitl_requests=hitl_requests,
        warnings=warnings,
    )
    goto = "human_review" if state.config.pause_for_hitl and hitl_requests else END
    return Command(
        update={
            "clause_reviews": _checkpoint_value(clause_reviews),
            "findings": _checkpoint_value(findings),
            "hitl_requests": _checkpoint_value(hitl_requests),
            "result": _checkpoint_value(result),
            "warnings": warnings,
        },
        goto=goto,
    )


def human_review_contract_findings(state: ContractReviewGraphState) -> Command[str]:
    state = _coerce_review_state(state)
    if state.result is None:
        raise ValueError("result is required before human review.")
    if not state.hitl_requests:
        return Command(goto=END)

    resume_payload = interrupt(
        {
            "type": "contract_review_hitl",
            "summary": {
                "overall_risk_level": state.result.risk_level,
                "finding_count": len(state.result.findings),
                "request_count": len(state.hitl_requests),
            },
            "requests": [request.model_dump(mode="json") for request in state.hitl_requests],
        }
    )
    decisions = _parse_human_decisions(resume_payload)
    result = _apply_human_decisions(state.result, decisions)
    return Command(
        update={
            "human_decisions": _checkpoint_value(decisions),
            "result": _checkpoint_value(result),
            "findings": _checkpoint_value(result.findings),
            "clause_reviews": _checkpoint_value(result.clause_reviews),
        },
        goto=END,
    )


def _review_single_clause_unit(
    unit: ClauseReviewWorkItem,
    *,
    rag_client: RagEvidenceClient,
    generation_client: ReviewGenerationClient,
    cfg: ContractReviewConfig,
) -> ClauseReviewResult:
    clause = unit.clause
    if not unit.clause_text.strip():
        return ClauseReviewResult(
            clause_id=clause.clause_id,
            clause_no=clause.clause_no,
            title=clause.title,
            target_node_ids=clause.member_node_ids,
            query="",
            warnings=["Clause has no reviewable text."],
        )

    evidence_result = rag_client.query_legal_db(
        unit.query,
        doc_types=cfg.doc_types,
        law_names=cfg.law_names,
        intent="normative",
        search_query=unit.clause_text,
        top_k=cfg.top_k,
    )
    sources = _sources_from_evidence(evidence_result, cfg)
    prompt = _build_generation_prompt(clause, unit.paragraphs, sources)
    findings, clause_warnings = _generate_review_findings_with_repair(
        generation_client,
        prompt=prompt,
        clause=clause,
        paragraphs=unit.paragraphs,
        sources=sources,
        cfg=cfg,
    )
    return ClauseReviewResult(
        clause_id=clause.clause_id,
        clause_no=clause.clause_no,
        title=clause.title,
        target_node_ids=clause.member_node_ids,
        risk_level=_max_risk_level(finding.risk_level for finding in findings),
        query=unit.query,
        law_context_status=str(evidence_result.get("law_context_status", "") or ""),
        source_count=len(sources),
        findings=findings,
        warnings=clause_warnings,
    )


def _review_clause_units(
    parse_result: ParseDocumentResult,
    paragraph_by_id: dict[str, ParagraphPreview],
    cfg: ContractReviewConfig,
) -> list[tuple[ClauseSummary, list[ParagraphPreview]]]:
    clauses = parse_result.clauses
    if cfg.max_clauses is not None:
        clauses = clauses[: cfg.max_clauses]
    if clauses:
        return [
            (
                clause,
                [paragraph_by_id[node_id] for node_id in clause.member_node_ids if node_id in paragraph_by_id],
            )
            for clause in clauses
        ]
    paragraph_ids = [paragraph.node_id for paragraph in parse_result.paragraphs]
    if not paragraph_ids:
        return []
    fallback = ClauseSummary(
        clause_id="document",
        clause_no="",
        title="Document",
        start_node_id=paragraph_ids[0],
        end_node_id=paragraph_ids[-1],
        member_node_ids=paragraph_ids,
    )
    return [(fallback, parse_result.paragraphs)]


def _candidate_validation_clause(
    parse_result: ParseDocumentResult,
    target_node_id: str,
    candidate_text: str,
) -> tuple[ClauseSummary, list[ParagraphPreview]]:
    paragraph_by_id = {paragraph.node_id: paragraph for paragraph in parse_result.paragraphs}
    target = paragraph_by_id.get(target_node_id)
    if target is None:
        raise ValueError(f"target_node_id {target_node_id!r} was not found in parse_result paragraphs.")

    clause = next(
        (item for item in parse_result.clauses if target_node_id in item.member_node_ids),
        None,
    )
    if clause is None and target.clause_id:
        clause = next((item for item in parse_result.clauses if item.clause_id == target.clause_id), None)

    if clause is None:
        clause = ClauseSummary(
            clause_id=target.clause_id or target_node_id,
            clause_no=target.clause_no,
            title="Candidate edit validation",
            start_node_id=target_node_id,
            end_node_id=target_node_id,
            member_node_ids=[target_node_id],
        )

    paragraphs = [
        paragraph_by_id[node_id]
        for node_id in clause.member_node_ids
        if node_id in paragraph_by_id
    ] or [target]
    return (
        clause,
        [
            paragraph.model_copy(update={"text_excerpt": candidate_text, "text_length": len(candidate_text)})
            if paragraph.node_id == target_node_id
            else paragraph
            for paragraph in paragraphs
        ],
    )


def _edit_validation_failure_reason(review: ClauseReviewResult) -> str:
    if not review.findings:
        return "재검증 결과 중간 이상의 리스크가 남아 있어 수정안을 반려했습니다."

    finding = max(review.findings, key=lambda item: _RISK_ORDER.get(item.risk_level, 0))
    risk_label = {
        "mid": "중간",
        "high": "높음",
        "crit": "치명",
    }.get(finding.risk_level, finding.risk_level)
    detail = finding.rationale or finding.recommendation or finding.human_question
    parts = [f"{risk_label} 리스크가 남아 있습니다."]
    if finding.title:
        parts.append(finding.title)
    if detail:
        parts.append(detail)
    return " ".join(parts)


def _clause_text(clause: ClauseSummary, paragraphs: Sequence[ParagraphPreview], max_chars: int) -> str:
    lines = []
    heading = " ".join(part for part in (clause.clause_no, clause.title) if part)
    if heading:
        lines.append(heading)
    for paragraph in paragraphs:
        text = paragraph.text_excerpt.strip()
        if text:
            lines.append(f"[{paragraph.node_id}] {text}")
    joined = "\n".join(lines)
    return joined[:max_chars]


def _build_rag_query(clause: ClauseSummary, clause_text: str) -> str:
    label = " ".join(part for part in (clause.clause_no, clause.title) if part).strip()
    return (
        "계약 조항의 법적 위험과 불공정하거나 문제될 수 있는 부분을 검토해 주세요.\n"
        f"조항: {label or clause.clause_id}\n"
        f"조항 내용:\n{clause_text}"
    )


def _sources_from_evidence(evidence_result: Mapping[str, Any], cfg: ContractReviewConfig) -> list[ContractReviewSource]:
    documents = evidence_result.get("documents") or []
    sources: list[ContractReviewSource] = []
    for raw in documents:
        if not isinstance(raw, Mapping):
            continue
        text = str(raw.get("text", "") or "")
        sources.append(
            ContractReviewSource(
                rank=_as_int(raw.get("rank")),
                source_id=str(raw.get("source_id", "") or ""),
                doc_type=str(raw.get("doc_type", "") or ""),
                law_name=str(raw.get("law_name", "") or ""),
                article_no=str(raw.get("article_no", "") or ""),
                citation=str(raw.get("citation", "") or ""),
                snippet=str(raw.get("snippet", "") or ""),
                text=text[: cfg.max_source_text_chars],
                score=raw.get("score"),
            )
        )
    return sources


def _build_generation_prompt(
    clause: ClauseSummary,
    paragraphs: Sequence[ParagraphPreview],
    sources: Sequence[ContractReviewSource],
) -> str:
    evidence = [
        {
            "source_id": source.source_id,
            "citation": source.citation,
            "doc_type": source.doc_type,
            "law_name": source.law_name,
            "article_no": source.article_no,
            "snippet": source.snippet,
            "text": source.text,
        }
        for source in sources
    ]
    paragraph_payload = [
        {
            "node_id": paragraph.node_id,
            "text": paragraph.text_excerpt,
            "clause_id": paragraph.clause_id,
            "subclause_id": paragraph.subclause_id,
        }
        for paragraph in paragraphs
    ]
    schema = {
        "findings": [
            {
                "risk_level": "none|low|mid|high|crit",
                "issue_type": "short machine label",
                "title": "short Korean user-facing title",
                "target_node_id": "paragraph node_id from clause_paragraphs",
                "selected_text": "exact risky substring in that paragraph, or empty string",
                "rationale": "Korean explanation of why this may be problematic, grounded in evidence",
                "recommendation": "Korean human-reviewable fix strategy",
                "replacement_text": "Korean replacement for selected_text, or empty string",
                "full_replacement_text": "Korean full paragraph replacement, or empty string",
                "human_question": "Korean question asking for specific missing information if no safe replacement can be suggested",
                "source_ids": ["source ids used"],
            }
        ]
    }
    return "\n\n".join(
        [
            "[clause]",
            json.dumps(
                {
                    "clause_id": clause.clause_id,
                    "clause_no": clause.clause_no,
                    "title": clause.title,
                    "paragraphs": paragraph_payload,
                },
                ensure_ascii=False,
            ),
            "[rag_evidence]",
            json.dumps(evidence, ensure_ascii=False),
            "[required_json_schema]",
            json.dumps(schema, ensure_ascii=False),
            "[language_requirement]",
            "사용자에게 표시되는 모든 필드(title, rationale, recommendation, replacement_text, "
            "full_replacement_text, human_question)는 한국어로 작성하세요.",
        ]
    )


def _generation_answer(result: Any) -> str:
    if isinstance(result, str):
        return result
    answer = getattr(result, "answer", None)
    if isinstance(answer, str):
        return answer
    return str(result)


def _generate_review_findings_with_repair(
    generation_client: ReviewGenerationClient,
    *,
    prompt: str,
    clause: ClauseSummary,
    paragraphs: Sequence[ParagraphPreview],
    sources: Sequence[ContractReviewSource],
    cfg: ContractReviewConfig,
) -> tuple[list[ContractReviewFinding], list[str]]:
    attempts: list[_ReviewGenerationAttempt] = []
    current_prompt = prompt
    max_attempts = cfg.max_generation_repair_attempts
    for attempt_no in range(1, max_attempts + 1):
        answer = _generate_answer_with_provider_retry(
            generation_client,
            prompt=current_prompt,
            cfg=cfg,
        )
        payload, parse_warning = _parse_generation_payload(answer)
        findings = _findings_from_payload(
            payload,
            clause=clause,
            paragraphs=paragraphs,
            sources=sources,
            max_sources=cfg.max_sources_per_finding,
        )
        validation_issues = _generation_validation_issues(
            payload,
            parse_warning=parse_warning,
            paragraphs=paragraphs,
            sources=sources,
        )
        attempt = _ReviewGenerationAttempt(
            attempt_no=attempt_no,
            answer=answer,
            payload=payload,
            parse_warning=parse_warning,
            validation_issues=validation_issues,
            findings=findings,
        )
        attempts.append(attempt)
        if not validation_issues:
            warnings = [parse_warning] if parse_warning else []
            if attempt_no > 1:
                warnings.append(f"Review generation repaired after {attempt_no} attempts.")
            return findings, warnings
        if attempt_no < max_attempts:
            logger.warning(
                "Contract review generation validation failed; retrying clause review "
                "(clause_id=%s, clause_no=%s, attempt=%s/%s, issues=%s)",
                clause.clause_id,
                clause.clause_no,
                attempt_no,
                max_attempts,
                _summarize_validation_issues(validation_issues),
            )
            current_prompt = _build_generation_repair_prompt(
                prompt,
                answer=answer,
                validation_issues=validation_issues,
                next_attempt=attempt_no + 1,
                max_attempts=max_attempts,
            )

    fallback = _best_generation_attempt(attempts)
    warnings = [
        (
            f"Review generation validation still failed after {max_attempts} attempts; "
            f"falling back to normalized output. Issues: {_summarize_validation_issues(fallback.validation_issues)}"
        )
    ]
    logger.warning(
        "Contract review generation validation failed after max attempts; using fallback "
        "(clause_id=%s, clause_no=%s, attempts=%s, issues=%s)",
        clause.clause_id,
        clause.clause_no,
        max_attempts,
        _summarize_validation_issues(fallback.validation_issues),
    )
    if fallback.parse_warning and fallback.parse_warning not in warnings[0]:
        warnings.append(fallback.parse_warning)
    return fallback.findings, warnings


def _generate_answer_with_provider_retry(
    generation_client: ReviewGenerationClient,
    *,
    prompt: str,
    cfg: ContractReviewConfig,
) -> str:
    max_attempts = cfg.max_generation_provider_retry_attempts
    last_exc: Exception | None = None
    attempts_used = 0
    for attempt_no in range(1, max_attempts + 1):
        attempts_used = attempt_no
        try:
            return _generation_answer(
                generation_client.generate(prompt, system_prompt=_CONTRACT_REVIEW_SYSTEM_PROMPT)
            )
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_generation_exception(exc) or attempt_no >= max_attempts:
                break
            delay = _provider_retry_delay(cfg.generation_provider_retry_base_delay_sec, attempt_no)
            logger.warning(
                "Contract review generation provider call failed; retrying "
                "(attempt=%s/%s, delay_sec=%.2f, error=%s)",
                attempt_no,
                max_attempts,
                delay,
                _truncate_text(str(exc), 1000),
            )
            if delay > 0:
                time.sleep(delay)
    if last_exc is not None:
        logger.warning(
            "Contract review generation provider call failed "
            "(attempts=%s/%s, retryable=%s, error=%s)",
            attempts_used,
            max_attempts,
            _is_retryable_generation_exception(last_exc),
            _truncate_text(str(last_exc), 1000),
        )
        raise last_exc
    raise RuntimeError("Review generation failed without an exception.")


def _is_retryable_generation_exception(exc: Exception) -> bool:
    text = str(exc).lower()
    retryable_markers = (
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "unavailable",
        "resource_exhausted",
        "rate limit",
        "quota",
        "temporarily",
        "timed out",
        "timeout",
    )
    return any(marker in text for marker in retryable_markers)


def _provider_retry_delay(base_delay_sec: float, attempt_no: int) -> float:
    return min(base_delay_sec * (2 ** (attempt_no - 1)), 30.0)


def _build_generation_repair_prompt(
    base_prompt: str,
    *,
    answer: str,
    validation_issues: Sequence[str],
    next_attempt: int,
    max_attempts: int,
) -> str:
    return "\n\n".join(
        [
            base_prompt,
            "[repair_instruction]",
            (
                "Your previous response failed validation. Return the full corrected JSON object only. "
                "Do not include markdown, explanations, or fields outside the requested schema."
            ),
            f"This is attempt {next_attempt} of {max_attempts}.",
            "[validation_failures]",
            json.dumps(list(validation_issues), ensure_ascii=False, indent=2),
            "[previous_response]",
            _truncate_text(answer, 6000),
        ]
    )


def _generation_validation_issues(
    payload: Mapping[str, Any],
    *,
    parse_warning: str | None,
    paragraphs: Sequence[ParagraphPreview],
    sources: Sequence[ContractReviewSource],
) -> list[str]:
    issues: list[str] = []
    if parse_warning:
        issues.append(parse_warning)
    try:
        typed_payload = _GeneratedReviewPayload.model_validate(payload)
    except ValidationError as exc:
        issues.append(f"Review generation schema validation failed: {_format_validation_error(exc)}")
        return issues

    paragraph_by_id = {paragraph.node_id: paragraph for paragraph in paragraphs}
    fallback_node_id = paragraphs[0].node_id if paragraphs else ""
    valid_source_ids = {source.source_id for source in sources if source.source_id}
    for index, finding in enumerate(typed_payload.findings, start=1):
        prefix = f"finding {index}"
        if not _risk_level_is_known(finding.risk_level):
            issues.append(
                f"{prefix}: risk_level {finding.risk_level!r} is invalid; use one of none, low, mid, high, crit."
            )
        risk_level = _normalize_risk_level(finding.risk_level)
        if risk_level == "none":
            continue
        target_node_id = finding.target_node_id or fallback_node_id
        target = paragraph_by_id.get(target_node_id)
        if target is None:
            issues.append(
                f"{prefix}: target_node_id {target_node_id!r} is not in clause_paragraphs; "
                f"use one of {_compact_values(paragraph_by_id)}."
            )
            target = paragraph_by_id.get(fallback_node_id)
        target_text = target.text_excerpt if target is not None else ""
        selected_text = finding.selected_text or finding.problematic_text
        if selected_text and target_text and selected_text not in target_text:
            issues.append(f"{prefix}: selected_text must be an exact substring of target_node_id paragraph text.")
        if finding.replacement_text and not selected_text:
            issues.append(f"{prefix}: replacement_text requires selected_text; use full_replacement_text for full paragraph edits.")
        if finding.replacement_text and selected_text and target_text and selected_text not in target_text:
            issues.append(f"{prefix}: replacement_text cannot be applied because selected_text is not in the target paragraph.")
        new_text = _candidate_edit_new_text(
            target_text,
            selected_text,
            replacement_text=finding.replacement_text,
            full_replacement_text=finding.full_replacement_text,
        )
        if target is not None and new_text:
            sibling_texts = [
                paragraph.text_excerpt
                for paragraph in paragraphs
                if paragraph.node_id != target.node_id
            ]
            issues.extend(
                f"{prefix}: {issue}"
                for issue in _proposed_edit_safety_issues(
                    target,
                    target_text=target_text,
                    new_text=new_text,
                    sibling_texts=sibling_texts,
                )
            )
        if sources and not finding.source_ids:
            issues.append(f"{prefix}: source_ids must include at least one supplied source_id.")
        elif valid_source_ids and finding.source_ids and not set(finding.source_ids).intersection(valid_source_ids):
            issues.append(f"{prefix}: source_ids must match supplied source ids; use one of {_compact_values(valid_source_ids)}.")
        if not (finding.replacement_text or finding.full_replacement_text or finding.human_question):
            issues.append(f"{prefix}: provide replacement_text, full_replacement_text, or human_question for HITL handling.")
    return issues


def _best_generation_attempt(attempts: Sequence[_ReviewGenerationAttempt]) -> _ReviewGenerationAttempt:
    return min(
        attempts,
        key=lambda attempt: (
            len(attempt.validation_issues),
            1 if not attempt.findings else 0,
            -len(attempt.findings),
            attempt.attempt_no,
        ),
    )


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors()[:5]:
        loc = ".".join(str(part) for part in error.get("loc", ())) or "payload"
        parts.append(f"{loc}: {error.get('msg', 'invalid value')}")
    return "; ".join(parts)


def _summarize_validation_issues(issues: Sequence[str], *, limit: int = 5) -> str:
    summary = "; ".join(issues[:limit])
    if len(issues) > limit:
        summary = f"{summary}; +{len(issues) - limit} more"
    return summary


def _risk_level_is_known(value: Any) -> bool:
    return str(value or "mid").strip().lower() in _RISK_LEVEL_ALIASES


def _compact_values(values: Mapping[str, Any] | set[str], *, limit: int = 6) -> str:
    items = list(values.keys() if isinstance(values, Mapping) else values)
    visible = ", ".join(repr(item) for item in items[:limit])
    if len(items) > limit:
        visible = f"{visible}, +{len(items) - limit} more"
    return visible or "[]"


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated]"


def _parse_generation_payload(answer: str) -> tuple[Mapping[str, Any], str | None]:
    cleaned = re.sub(r"\[ANSWERABLE:(yes|no)\]\s*$", "", answer.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned.strip(), flags=re.IGNORECASE | re.MULTILINE)
    start = min([idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx >= 0], default=-1)
    if start > 0:
        cleaned = cleaned[start:]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        try:
            parsed, end = json.JSONDecoder().raw_decode(cleaned)
        except json.JSONDecodeError:
            return {"findings": []}, f"Could not parse review generation JSON: {exc.msg}."
        trailing = cleaned[end:].strip()
        if trailing:
            payload, normalize_warning = _normalize_generation_payload(parsed)
            return payload, normalize_warning or "Ignored trailing text after review generation JSON."
        return _normalize_generation_payload(parsed)
    return _normalize_generation_payload(parsed)


def _normalize_generation_payload(parsed: Any) -> tuple[Mapping[str, Any], str | None]:
    if isinstance(parsed, list):
        return {"findings": parsed}, None
    if isinstance(parsed, Mapping):
        return parsed, None
    return {"findings": []}, "Review generation JSON must be an object or list."


def _findings_from_payload(
    payload: Mapping[str, Any],
    *,
    clause: ClauseSummary,
    paragraphs: Sequence[ParagraphPreview],
    sources: Sequence[ContractReviewSource],
    max_sources: int,
) -> list[ContractReviewFinding]:
    raw_findings = payload.get("findings") or []
    if not isinstance(raw_findings, Sequence) or isinstance(raw_findings, (str, bytes)):
        return []
    paragraph_by_id = {paragraph.node_id: paragraph for paragraph in paragraphs}
    fallback_node_id = paragraphs[0].node_id if paragraphs else clause.start_node_id
    findings: list[ContractReviewFinding] = []
    for index, raw in enumerate(raw_findings):
        if not isinstance(raw, Mapping):
            continue
        raw_target_node_id = str(raw.get("target_node_id", "") or fallback_node_id)
        target = paragraph_by_id.get(raw_target_node_id)
        if target is None:
            target = paragraph_by_id.get(fallback_node_id)
        target_node_id = target.node_id if target is not None else fallback_node_id
        target_text = target.text_excerpt if target is not None else ""
        selected_text = str(raw.get("selected_text", "") or raw.get("problematic_text", "") or "")
        if selected_text and selected_text not in target_text:
            selected_text = ""
        risk_level = _normalize_risk_level(raw.get("risk_level", raw.get("severity")))
        if risk_level == "none":
            continue
        selected_sources = _select_sources(raw.get("source_ids"), sources, max_sources)
        if not selected_sources:
            continue
        proposed_edit = _build_proposed_edit(raw, target_node_id, target_text, selected_text)
        if proposed_edit is not None and target is not None:
            sibling_texts = [
                paragraph.text_excerpt
                for paragraph in paragraphs
                if paragraph.node_id != target_node_id
            ]
            if _proposed_edit_safety_issues(
                target,
                target_text=target_text,
                new_text=proposed_edit.new_text,
                sibling_texts=sibling_texts,
            ):
                proposed_edit = None
        findings.append(
            ContractReviewFinding(
                finding_id=f"{clause.clause_id}:finding:{index + 1}",
                clause_id=clause.clause_id,
                clause_no=clause.clause_no,
                target_node_ids=[target_node_id],
                risk_level=risk_level,
                issue_type=str(raw.get("issue_type", "") or "contract_risk"),
                title=str(raw.get("title", "") or "Contract review finding"),
                problematic_text=selected_text,
                rationale=str(raw.get("rationale", "") or ""),
                recommendation=str(raw.get("recommendation", "") or ""),
                human_question=str(raw.get("human_question", "") or ""),
                sources=selected_sources,
                annotation=_build_annotation(
                    raw,
                    target_node_id,
                    target_text,
                    selected_text,
                    risk_level,
                    selected_sources,
                ),
                proposed_edit=proposed_edit,
            )
        )
    return findings


def _normalize_risk_level(value: Any) -> RiskLevel:
    normalized = str(value or "mid").strip().lower()
    return _RISK_LEVEL_ALIASES.get(normalized, "mid")


def _select_sources(
    raw_source_ids: Any,
    sources: Sequence[ContractReviewSource],
    max_sources: int,
) -> list[ContractReviewSource]:
    if isinstance(raw_source_ids, Sequence) and not isinstance(raw_source_ids, (str, bytes)):
        wanted = {str(source_id) for source_id in raw_source_ids}
        selected = [source for source in sources if source.source_id in wanted]
        if selected:
            return selected[:max_sources]
    return list(sources[:max_sources])


def _build_annotation(
    raw: Mapping[str, Any],
    target_node_id: str,
    target_text: str,
    selected_text: str,
    risk_level: RiskLevel,
    sources: Sequence[ContractReviewSource],
) -> TextAnnotation:
    occurrence_index = None
    if selected_text and target_text.count(selected_text) > 1:
        occurrence_index = 0
    title = str(raw.get("title", "") or "Contract review finding")
    rationale = str(raw.get("rationale", "") or "")
    source_note = _source_note(sources)
    note = "\n".join(part for part in (rationale, source_note) if part)
    return TextAnnotation(
        target_kind="paragraph",
        target_id=target_node_id,
        selected_text=selected_text or None,
        occurrence_index=occurrence_index,
        label=f"{_RISK_LABELS[risk_level]}: {title}",
        color=_RISK_COLORS[risk_level],
        note=note,
    )


def _build_proposed_edit(
    raw: Mapping[str, Any],
    target_node_id: str,
    target_text: str,
    selected_text: str,
) -> TextEdit | None:
    full_replacement = str(raw.get("full_replacement_text", "") or "")
    replacement = str(raw.get("replacement_text", "") or "")
    new_text = _candidate_edit_new_text(
        target_text,
        selected_text,
        replacement_text=replacement,
        full_replacement_text=full_replacement,
    )
    if not new_text or new_text == target_text:
        return None
    return TextEdit(
        target_kind="paragraph",
        target_id=target_node_id,
        expected_text_hash=_text_hash(target_text),
        new_text=new_text,
        reason=str(raw.get("recommendation", "") or raw.get("title", "") or "Contract review suggestion"),
    )


def _candidate_edit_new_text(
    target_text: str,
    selected_text: str,
    *,
    replacement_text: str,
    full_replacement_text: str,
) -> str:
    if full_replacement_text:
        return full_replacement_text
    if selected_text and replacement_text and selected_text in target_text:
        return target_text.replace(selected_text, replacement_text, 1)
    return ""


def _proposed_edit_safety_issues(
    target: ParagraphPreview,
    *,
    target_text: str,
    new_text: str,
    sibling_texts: Sequence[str],
) -> list[str]:
    issues: list[str] = []
    normalized_new_text = _normalize_ws(new_text)
    for sibling_text in sibling_texts:
        normalized_sibling = _normalize_ws(sibling_text)
        if len(normalized_sibling) >= 20 and normalized_sibling in normalized_new_text:
            issues.append("proposed edit includes text from a neighboring paragraph; keep edits scoped to the target paragraph.")
            break

    target_prefixes = _numbered_line_prefixes(target_text)
    new_prefixes = _numbered_line_prefixes(new_text)
    if target_prefixes and new_prefixes:
        target_prefix = target_prefixes[0]
        if new_prefixes[0] != target_prefix:
            issues.append(
                f"proposed edit changes the target paragraph numbering from {target_prefix!r} to {new_prefixes[0]!r}."
            )
        if any(prefix != target_prefix for prefix in new_prefixes):
            issues.append("proposed edit contains another top-level numbered subclause.")

    category = target.category
    if category == ParagraphCategory.CLAUSE_HEADING:
        if _looks_like_clause_heading(target_text) and not _looks_like_clause_heading(new_text):
            issues.append("proposed edit replaces a clause heading with non-heading body text.")
        if _numbered_line_prefixes(new_text):
            issues.append("proposed edit targets a clause heading but starts with subclause numbering.")
    return issues


def _numbered_line_prefixes(text: str) -> list[str]:
    prefixes: list[str] = []
    for line in text.splitlines() or [text]:
        match = re.match(r"^\s*(\d+)\.", line)
        if match:
            prefixes.append(match.group(1))
    return prefixes


def _looks_like_clause_heading(text: str) -> bool:
    return bool(re.match(r"^\s*제\s*\d+\s*조", text.strip()))


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def _render_findings_html(
    findings: Sequence[ContractReviewFinding],
    *,
    cfg: ContractReviewConfig,
    render_document: DocumentInput | None,
    render_source_path: str | None,
    warnings: list[str],
) -> str | None:
    if not cfg.include_review_html or (render_document is None and render_source_path is None):
        return None
    annotations = [finding.annotation for finding in findings if finding.annotation is not None]
    if not annotations:
        return None
    result = render_review_html(
        document=render_document,
        source_path=render_source_path,
        annotations=annotations,
        title=cfg.review_title,
    )
    if not result.ok:
        warnings.extend(issue.message for issue in result.validation.issues)
        return None
    return result.html


def _source_note(sources: Sequence[ContractReviewSource]) -> str:
    labels = [
        source.citation or source.source_id
        for source in sources
        if source.citation or source.source_id
    ]
    if not labels:
        return ""
    return "Sources: " + "; ".join(labels[:3])


def _max_risk_level(levels: Sequence[RiskLevel] | Any) -> RiskLevel:
    max_level: RiskLevel = "none"
    for level in levels:
        normalized = _normalize_risk_level(level)
        if _RISK_ORDER[normalized] > _RISK_ORDER[max_level]:
            max_level = normalized
    return max_level


def _clause_risk_counts(clause_reviews: Sequence[ClauseReviewResult]) -> dict[RiskLevel, int]:
    counts: dict[RiskLevel, int] = {level: 0 for level in _RISK_LEVELS}
    for review in clause_reviews:
        counts[review.risk_level] += 1
    return counts


def _build_hitl_requests(
    findings: Sequence[ContractReviewFinding],
    cfg: ContractReviewConfig,
) -> list[ContractReviewHumanRequest]:
    requests: list[ContractReviewHumanRequest] = []
    for finding in findings:
        if _RISK_ORDER[finding.risk_level] < _RISK_ORDER[cfg.hitl_min_risk_level]:
            continue
        source_citations = [
            source.citation or source.source_id
            for source in finding.sources
            if source.citation or source.source_id
        ]
        if finding.proposed_edit is not None:
            requests.append(
                ContractReviewHumanRequest(
                    request_id=f"{finding.finding_id}:hitl",
                    finding_id=finding.finding_id,
                    clause_id=finding.clause_id,
                    clause_no=finding.clause_no,
                    risk_level=finding.risk_level,
                    title=finding.title,
                    kind="suggested_edit",
                    prompt="제안된 수정안을 적용하기 전에 검토하세요.",
                    guidance=finding.recommendation,
                    selected_text=finding.problematic_text,
                    proposed_edit=finding.proposed_edit,
                    diff=_text_diff(
                        finding.problematic_text or "Current paragraph",
                        finding.proposed_edit.new_text,
                    ),
                    source_citations=source_citations,
                    allowed_actions=["accept", "reject", "feedback"],
                )
            )
            continue

        requests.append(
            ContractReviewHumanRequest(
                request_id=f"{finding.finding_id}:hitl",
                finding_id=finding.finding_id,
                clause_id=finding.clause_id,
                clause_no=finding.clause_no,
                risk_level=finding.risk_level,
                title=finding.title,
                kind="human_input",
                prompt=finding.human_question
                or "이 문제를 안전하게 수정하기 위해 필요한 사업상 또는 법무상 정보를 입력하세요.",
                guidance=finding.recommendation,
                selected_text=finding.problematic_text,
                source_citations=source_citations,
                allowed_actions=["provide_info", "manual_edit", "reject", "feedback"],
            )
        )
    return requests


def _attach_human_requests(
    findings: Sequence[ContractReviewFinding],
    hitl_requests: Sequence[ContractReviewHumanRequest],
) -> list[ContractReviewFinding]:
    request_by_finding_id = {request.finding_id: request for request in hitl_requests}
    return [
        finding.model_copy(update={"human_request": request_by_finding_id.get(finding.finding_id)})
        for finding in findings
    ]


def _replace_clause_review_findings(
    clause_reviews: Sequence[ClauseReviewResult],
    findings: Sequence[ContractReviewFinding],
) -> list[ClauseReviewResult]:
    findings_by_clause: dict[str, list[ContractReviewFinding]] = {}
    for finding in findings:
        findings_by_clause.setdefault(finding.clause_id, []).append(finding)
    return [
        review.model_copy(update={"findings": findings_by_clause.get(review.clause_id, [])})
        for review in clause_reviews
    ]


def _parse_human_decisions(payload: Any) -> list[ContractReviewHumanDecision]:
    if payload is None:
        return []
    raw_decisions: Any
    if isinstance(payload, Mapping):
        raw_decisions = payload.get("decisions")
        if raw_decisions is None and "finding_id" in payload:
            raw_decisions = [payload]
    else:
        raw_decisions = payload
    if isinstance(raw_decisions, Mapping):
        raw_decisions = [
            {"finding_id": finding_id, **decision}
            if isinstance(decision, Mapping)
            else {"finding_id": finding_id, "action": decision}
            for finding_id, decision in raw_decisions.items()
        ]
    if not isinstance(raw_decisions, Sequence) or isinstance(raw_decisions, (str, bytes)):
        return []

    decisions: list[ContractReviewHumanDecision] = []
    for raw in raw_decisions:
        if not isinstance(raw, Mapping):
            continue
        try:
            decisions.append(ContractReviewHumanDecision.model_validate(raw))
        except ValueError:
            continue
    return decisions


def _apply_human_decisions(
    result: ContractReviewResult,
    decisions: Sequence[ContractReviewHumanDecision],
) -> ContractReviewResult:
    status_by_finding_id = {
        decision.finding_id: _status_from_human_decision(decision)
        for decision in decisions
    }
    findings = [
        finding.model_copy(update={"status": status_by_finding_id.get(finding.finding_id, finding.status)})
        for finding in result.findings
    ]
    clause_reviews = _replace_clause_review_findings(result.clause_reviews, findings)
    return result.model_copy(
        update={
            "findings": findings,
            "clause_reviews": clause_reviews,
            "human_decisions": list(decisions),
        }
    )


def _status_from_human_decision(decision: ContractReviewHumanDecision) -> SuggestionStatus:
    if decision.action == "accept":
        return "accepted"
    if decision.action == "reject":
        return "rejected"
    return "feedback"


def _text_diff(before: str, after: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="current",
            tofile="suggested",
            lineterm="",
        )
    )


def _split_env_list(name: str) -> list[str]:
    return [part.strip() for part in os.getenv(name, "").split(",") if part.strip()]


def _parse_optional_int_env(
    name: str,
    warnings: list[str],
) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        warnings.append(f"{name} must be an integer. Current value: {raw!r}.")
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


__all__ = [
    "ClauseReviewResult",
    "ContractReviewClients",
    "ContractReviewConfig",
    "ContractEditRiskValidationResult",
    "ContractReviewEnvStatus",
    "ContractReviewFinding",
    "ContractReviewGraphState",
    "ContractReviewHumanDecision",
    "ContractReviewHumanRequest",
    "ContractReviewResult",
    "ContractReviewSource",
    "HitlDecisionAction",
    "HitlRequestKind",
    "ClauseReviewWorkItem",
    "RagEvidenceClient",
    "ReviewContractRequest",
    "ReviewGenerationClient",
    "RiskLevel",
    "SuggestionStatus",
    "build_contract_review_graph",
    "build_contract_review_clients_from_env",
    "check_contract_review_env",
    "review_contract_document",
    "review_contract_document_from_env",
    "review_parsed_contract",
    "validate_contract_edit_risk",
]
