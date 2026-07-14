"""generation 서비스 패키지 공개 API."""

from .llm_client import generate_answer, stream_answer
from .pipeline import (
    DEFAULT_SYSTEM_PROMPT,
    LegalDbCitation,
    LegalDbDocument,
    LegalDbQueryFilters,
    LegalDbQueryResult,
    RagPipeline,
    RagPipelineConfig,
    RagResult,
    build_user_prompt_with_limit,
)
from .service import GenerationConfig, GenerationResult, GenerationService

__all__ = [
    "GenerationService",
    "LegalDbCitation",
    "LegalDbDocument",
    "LegalDbQueryFilters",
    "LegalDbQueryResult",
    "RagPipeline",
    "generate_answer",
    "stream_answer",
]
