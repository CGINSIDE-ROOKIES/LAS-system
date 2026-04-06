"""Minimal LangGraph-ready state wrappers for IR v2."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field

from .ir_types import DocIR, ParagraphIR


class DocumentProcessState(BaseModel):
    """Top-level state for document parse/categorization stages."""

    target_file: Path = Field(default=Path())
    doc_ir: DocIR | None = None

    # Collector for parallel paragraph workers.
    paragraph_updates_temp: Annotated[
        list[tuple[int, ParagraphIR]],
        lambda left, right: [] if right == [] else left + right,
    ] = Field(default=[])

    preprocess_state: Literal["uncategorized", "prelim", "finished"] = Field(
        default="uncategorized"
    )

    @computed_field
    def formatted_content(self) -> list[str]:
        if self.doc_ir is None:
            return []
        return [paragraph.normalized_text for paragraph in self.doc_ir.paragraphs]


class ParagraphProcessState(BaseModel):
    """Per-paragraph worker state for categorization/parsing."""

    paragraph_idx: int
    paragraph_ir: ParagraphIR


__all__ = ["DocumentProcessState", "ParagraphProcessState"]
