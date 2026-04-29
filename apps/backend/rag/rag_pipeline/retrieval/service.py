"""검색 파이프라인 설정 모듈."""

from __future__ import annotations

from dataclasses import dataclass

from .common import DEFAULT_EMBEDDING_MODEL, DEFAULT_OPENAI_API_BASE_URL


@dataclass
class RetrievalConfig:
    """RagPipeline retrieval 설정."""

    # 연결 정보
    qdrant_url: str
    qdrant_collections: list[str]
    opensearch_url: str
    opensearch_indices: list[str]
    qdrant_vector_name_map: dict[str, str] | None = None  # 컬렉션별 named vector 매핑
    qdrant_api_key: str | None = None
    opensearch_api_key: str | None = None
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    # BM25 match 대상 필드명(인덱스 매핑에 맞춰 변경 가능)
    opensearch_search_text_field: str = "search_text"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_api_key: str | None = None
    embedding_api_base_url: str = DEFAULT_OPENAI_API_BASE_URL
    embedding_dimensions: int | None = None

    # 파이프라인 파라미터
    top_k: int = 5
    # fuse/보강 정책을 위해 top_k보다 넉넉히 수집하는 후보 수
    candidate_k: int = 30
    rrf_k: int = 60
    timeout: int = 60
    auto_law_boost: bool = True
    law_boost_score: float = 0.003
    min_law_contexts: int = 1
    normative_law_ratio: float = 0.6       # normative law 슬롯 최대 비율
    law_slot_min_ratio: float = 0.2        # normative law 슬롯 최소 비율
    law_slot_score_threshold: float = 0.5  # law 슬롯 포함 기준 벡터 유사도 임계값
    max_content_chars: int = 1200
    max_total_chars: int = 6000
    min_chunk_text_len: int = 100
