"""retrieval 서비스 패키지 공개 API."""

from .common import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingError,
    LLMError,
    LLMTimeoutError,
    RetrievalError,
    dedup_normalized_rows,
    embed_query,
    normalize_source_id,
    UpstreamHTTPError,
    UpstreamNetworkError,
    UpstreamTimeoutError,
)
from .context import (
    build_llm_context_rows,
    build_llm_context_text,
    clean_content,
    truncate_on_semantic_boundary,
)
from .fusion import fuse_rrf
from .opensearch import search_bm25
from .qdrant import search_qdrant
from .ranking import (
    LAW_CONTEXT_CASE_ONLY,
    LAW_CONTEXT_MISSING,
    LAW_CONTEXT_OK,
    LAW_CONTEXT_SUPPLEMENTED,
    apply_law_boost,
    rank_rows,
    select_llm_rows,
    select_rows_with_law_policy,
)
from .service import RetrievalConfig

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingError",
    "LLMError",
    "LLMTimeoutError",
    "RetrievalConfig",
    "RetrievalError",
    "LAW_CONTEXT_OK",
    "LAW_CONTEXT_MISSING",
    "LAW_CONTEXT_SUPPLEMENTED",
    "LAW_CONTEXT_CASE_ONLY",
    "UpstreamHTTPError",
    "UpstreamNetworkError",
    "UpstreamTimeoutError",
    "apply_law_boost",
    "build_llm_context_rows",
    "build_llm_context_text",
    "clean_content",
    "dedup_normalized_rows",
    "embed_query",
    "fuse_rrf",
    "rank_rows",
    "select_rows_with_law_policy",
    "normalize_source_id",
    "search_bm25",
    "search_qdrant",
    "select_llm_rows",
    "truncate_on_semantic_boundary",
]
