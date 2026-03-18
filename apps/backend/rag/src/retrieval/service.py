"""검색 파이프라인 서비스.

전체 retrieval 흐름을 조립한다:
  search_qdrant + search_bm25 → fuse_rrf → apply_law_boost → select_llm_rows → build_llm_context_rows
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .common import DEFAULT_EMBEDDING_MODEL
from .context import build_llm_context_rows
from .fusion import fuse_rrf
from .opensearch import search_bm25
from .qdrant import search_qdrant
from .ranking import apply_law_boost, select_llm_rows


@dataclass
class RetrievalConfig:
    """RetrievalService 연결 및 파이프라인 설정."""

    # 연결 정보
    qdrant_url: str
    qdrant_collection: str
    opensearch_url: str
    opensearch_index: str
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


@dataclass
class RetrievalResult:
    """retrieve() 반환값."""

    contexts: list[dict[str, Any]]
    law_context_added: bool


class RetrievalService:
    def __init__(self, config: RetrievalConfig) -> None:
        self._cfg = config

    @classmethod
    def from_env(cls) -> RetrievalService:
        """환경변수에서 설정을 읽어 인스턴스를 생성한다."""
        config = RetrievalConfig(
            qdrant_url=os.environ["QDRANT_URL"],
            qdrant_collection=os.environ["QDRANT_COLLECTION"],
            qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
            opensearch_url=os.environ["OPENSEARCH_URL"],
            opensearch_index=os.environ["OPENSEARCH_INDEX"],
            opensearch_api_key=os.getenv("OPENSEARCH_API_KEY") or None,
            opensearch_username=os.getenv("OPENSEARCH_USERNAME") or None,
            opensearch_password=os.getenv("OPENSEARCH_PASSWORD") or None,
            embedding_model=os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        )
        return cls(config)

    def retrieve(
        self,
        question: str,
        *,
        doc_types: list[str] | None = None,
        law_names: list[str] | None = None,
    ) -> RetrievalResult:
        """질문에 대해 전체 검색 파이프라인을 실행하고 LLM 컨텍스트를 반환한다."""
        cfg = self._cfg
        candidate_k = max(cfg.top_k, cfg.candidate_k)

        # 1. 벡터 검색 + BM25 검색
        qdrant_rows = search_qdrant(
            question,
            candidate_k,
            qdrant_url=cfg.qdrant_url,
            collection=cfg.qdrant_collection,
            timeout=cfg.timeout,
            embedding_model=cfg.embedding_model,
            api_key=cfg.qdrant_api_key,
            doc_types=doc_types,
            law_names=law_names,
            dedup=True,
            fetch_multiplier=2,
        )
        bm25_rows = search_bm25(
            question,
            candidate_k,
            opensearch_url=cfg.opensearch_url,
            index_name=cfg.opensearch_index,
            timeout=cfg.timeout,
            api_key=cfg.opensearch_api_key,
            username=cfg.opensearch_username,
            password=cfg.opensearch_password,
            doc_types=doc_types,
            law_names=law_names,
            dedup=True,
            fetch_multiplier=5,
        )

        # 2. RRF 융합
        rrf_rows = fuse_rrf(qdrant_rows, bm25_rows, rrf_k=cfg.rrf_k, top_k=cfg.top_k)

        # 3. Law 문서 점수 가산 후 재정렬
        rrf_rows = apply_law_boost(
            rrf_rows,
            question=question,
            enabled=cfg.auto_law_boost,
            law_boost_score=cfg.law_boost_score,
        )[: max(1, cfg.top_k)]

        # 4. LLM 컨텍스트 빌드
        llm_rows, law_context_added = select_llm_rows(
            rrf_rows,
            top_k=cfg.top_k,
            min_law_contexts=cfg.min_law_contexts,
        )
        contexts = build_llm_context_rows(
            llm_rows,
            max_content_chars=cfg.max_content_chars,
            max_total_chars=cfg.max_total_chars,
        )

        return RetrievalResult(contexts=contexts, law_context_added=law_context_added)
