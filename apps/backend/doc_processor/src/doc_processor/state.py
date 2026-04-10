from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, Field

from document_processor import DocIR

from .types import Phase1Analysis, Phase1Result, RelevanceMode, WorkflowDelta, WorkflowMeta


class Phase1Config(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    relevance_mode: RelevanceMode = RelevanceMode.KEYWORD_THEN_LLM
    relevance_llm_profile: str = "relevance"
    boundary_llm_profile: str = "boundary"
    label_llm_profile: str = "label"
    prompt_profile: str = "default"
    relevance_preview_paragraphs: int = 40
    relevance_ambiguity_threshold: int = 2
    boundary_review_enabled: bool = True
    label_review_enabled: bool = True
    max_concurrent_workers: int = 4
    console_logging_enabled: bool = True
    console_log_level: str = "INFO"
    langfuse_enabled: bool | None = None
    langfuse_trace_name: str = "doc_processor.phase1"
    langfuse_user_id: str | None = None
    langfuse_session_id: str | None = None
    langfuse_tags: list[str] = Field(default_factory=lambda: ["phase1"])
    langfuse_metadata: dict[str, str] = Field(default_factory=dict)
    langfuse_environment: str | None = None
    langfuse_release: str | None = None
    langfuse_flush_at_end: bool = True
    relevance_model_override: Any | None = Field(default=None, exclude=True)
    boundary_model_override: Any | None = Field(default=None, exclude=True)
    label_model_override: Any | None = Field(default=None, exclude=True)


class WorkflowState(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    target_file: str | Path | None = None
    base_doc: DocIR | None = None
    working_doc: DocIR | None = None
    phase1_config: Phase1Config = Field(default_factory=Phase1Config)
    phase1_analysis: Phase1Analysis | None = None
    phase1_result: Phase1Result | None = None
    active_review_unit_id: str | None = None
    boundary_review_results: Annotated[list[dict[str, Any]], operator.add] = Field(default_factory=list)
    label_review_results: Annotated[list[dict[str, Any]], operator.add] = Field(default_factory=list)
    current_version: int = 0
    history: list[WorkflowDelta] = Field(default_factory=list)
    errors: Annotated[list[str], operator.add] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
