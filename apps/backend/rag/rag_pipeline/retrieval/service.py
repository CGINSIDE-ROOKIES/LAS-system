"""검색 파이프라인 설정 모듈."""

from __future__ import annotations

from dataclasses import dataclass

from .common import DEFAULT_EMBEDDING_MODEL


@dataclass
class RetrievalConfig:
    """RagPipeline retrieval 설정."""

    # 연결 정보
    qdrant_url: str
    qdrant_collections: list[str]
    opensearch_url: str
    opensearch_index: str
    qdrant_vector_name_map: dict[str, str] | None = None  # 컬렉션별 named vector 매핑
    qdrant_api_key: str | None = None
    opensearch_api_key: str | None = None
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    embedding_model: str = DEFAULT_EMBEDDING_MODEL

    # 파이프라인 파라미터
    top_k: int = 5
    candidate_k: int = 30
    rrf_k: int = 60
    timeout: int = 120
    auto_law_boost: bool = True
    law_boost_score: float = 0.003
    min_law_contexts: int = 1
    max_content_chars: int = 1200
    max_total_chars: int = 6000

