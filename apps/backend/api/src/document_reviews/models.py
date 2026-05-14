from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from doc_processor.contract_review import RiskLevel
from doc_processor.parser_types import RelevanceMode

DocumentReviewStatus = Literal["queued", "running", "hitl_waiting", "applying", "completed", "failed"]
DocumentReviewStage = Literal[
    "upload_saved",
    "parser_started",
    "parser_completed",
    "review_started",
    "review_progress",
    "hitl_waiting",
    "apply_started",
    "apply_completed",
    "completed",
    "failed",
]
PreviewKind = Literal["parser", "risk", "edited", "latest"]
DecisionAction = Literal["accept", "reject", "feedback"]


class DocumentReviewOptions(BaseModel):
    relevance_mode: RelevanceMode = RelevanceMode.KEYWORD_THEN_LLM
    boundary_review_enabled: bool = True
    label_review_enabled: bool = True
    parser_max_concurrent_workers: int = Field(default=4, ge=1, le=32)
    parser_llm_repair_max_attempts: int = Field(default=3, ge=1, le=5)
    prompt_profile: str = Field(default="default", min_length=1, max_length=80)
    top_k: int = Field(default=8, ge=1, le=50)
    max_clauses: int | None = Field(default=None, ge=1)
    max_clause_chars: int = Field(default=4000, ge=500)
    max_source_text_chars: int = Field(default=1200, ge=100)
    max_sources_per_finding: int = Field(default=3, ge=1)
    max_concurrent_risk_reviews: int = Field(default=4, ge=1, le=32)
    max_generation_repair_attempts: int = Field(default=3, ge=1, le=5)
    max_generation_provider_retry_attempts: int = Field(default=3, ge=1, le=8)
    generation_provider_retry_base_delay_sec: float = Field(default=1.0, ge=0.0, le=60.0)
    doc_types: list[str] | None = Field(default_factory=lambda: ["law", "prec", "detc", "decc", "expc"])
    law_names: list[str] | None = None
    include_review_html: bool = True
    review_title: str = Field(default="계약 리스크 검토", min_length=1, max_length=120)
    hitl_min_risk_level: RiskLevel = "low"

    @field_validator("doc_types", "law_names")
    @classmethod
    def _strip_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [item.strip() for item in value if item and item.strip()]
        return cleaned or None

    @classmethod
    def from_multipart_options(cls, raw_options: str | None) -> "DocumentReviewOptions":
        if not raw_options:
            return cls()
        try:
            payload = json.loads(raw_options)
        except json.JSONDecodeError as exc:
            raise ValueError("options must be a JSON object.") from exc
        if not isinstance(payload, dict):
            raise ValueError("options must be a JSON object.")
        return cls.model_validate(payload)


class CreateDocumentReviewResponse(BaseModel):
    review_id: str
    status: DocumentReviewStatus
    events_url: str


class DocumentReviewSummary(BaseModel):
    review_id: str
    status: DocumentReviewStatus
    stage: DocumentReviewStage
    progress: float = Field(ge=0.0, le=1.0)
    source_name: str
    source_doc_type: str | None = None
    current_preview_kind: Literal["parser", "risk", "edited"] | None = None
    risk_counts: dict[str, int] = Field(default_factory=dict)
    artifact_flags: dict[str, bool] = Field(default_factory=dict)
    preview_url: str
    events_url: str
    suggestions_url: str
    download_url: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class DocumentReviewSuggestion(BaseModel):
    finding_id: str
    request_id: str | None = None
    clause_id: str | None = None
    risk_level: str | None = None
    status: Literal["pending", "accepted", "rejected", "feedback"]
    title: str = ""
    kind: str = "finding"
    prompt: str = ""
    guidance: str = ""
    selected_text: str = ""
    diff: str | None = None
    source_citations: list[str] = Field(default_factory=list)
    proposed_edit: dict[str, Any] | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class DocumentReviewSuggestionsResponse(BaseModel):
    items: list[DocumentReviewSuggestion]
    total: int


class SuggestionDecisionRequest(BaseModel):
    action: DecisionAction
    comment: str | None = Field(default=None, max_length=2000)


class ResumeDocumentReviewResponse(BaseModel):
    review_id: str
    status: DocumentReviewStatus
    stage: DocumentReviewStage
    decisions_applied: int


class ApplyDocumentReviewResponse(BaseModel):
    review_id: str
    status: DocumentReviewStatus
    stage: DocumentReviewStage
    edits_applied: int
    skipped_conflicts: list[str] = Field(default_factory=list)
    download_url: str | None = None
    preview_url: str
    warnings: list[str] = Field(default_factory=list)
