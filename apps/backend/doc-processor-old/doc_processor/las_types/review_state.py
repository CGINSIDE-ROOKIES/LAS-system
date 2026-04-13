from pydantic import BaseModel, Field

from pathlib import Path
from typing import Annotated

from .ir_types import IRGroup
from .style_types import StyleMap
from .annotation_types import ArticleAnnotations
from .risk_types import ArticleRiskReport


class ReviewState(BaseModel):
    """Top-level state for the review pipeline."""
    target_file: Path = Field(default=Path())

    # Stage 1: parser output
    ir_groups: list[IRGroup] = Field(default=[])
    style_map: StyleMap | None = None

    # Stage 2: risk analysis (collector pattern — same as DocumentState.ir_groups_temp)
    # empty list [] acts as a clear signal
    analysis_temp: Annotated[
        list[tuple[int, ArticleRiskReport, ArticleAnnotations]],
        lambda left, right: [] if right == [] else left + right
    ] = Field(default=[])

    # Stage 2 consolidated
    annotations: dict[int, ArticleAnnotations] = Field(default_factory=dict)
    risk_reports: list[ArticleRiskReport] = Field(default=[])

    # Stage 3: output
    html_output: str = ""


class ArticleAnalysisState(BaseModel):
    """Per-article worker state, sent via Send()."""
    group_idx: int
    ir_group: IRGroup
