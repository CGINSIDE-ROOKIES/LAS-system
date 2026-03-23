"""retrieval 서비스 패키지 공개 API."""

from .common import (
    DEFAULT_EMBEDDING_MODEL,
    RetrievalError,
    dedup_normalized_rows,
    embed_query,
    normalize_source_id,
)
from .context import build_llm_context_rows, build_llm_context_text
from .fusion import fuse_rrf
from .opensearch import search_bm25
from .qdrant import search_qdrant
from .ranking import apply_law_boost, is_normative_query, rank_rows, select_llm_rows, select_rows_with_law_policy
from .service import RetrievalConfig

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "RetrievalConfig",
    "RetrievalError",
    "apply_law_boost",
    "build_llm_context_rows",
    "build_llm_context_text",
    "dedup_normalized_rows",
    "embed_query",
    "fuse_rrf",
    "is_normative_query",
    "rank_rows",
    "select_rows_with_law_policy",
    "normalize_source_id",
    "search_bm25",
    "search_qdrant",
    "select_llm_rows",
]
