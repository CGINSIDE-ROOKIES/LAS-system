"""Qdrant 벡터 검색 서비스."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from .common import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_OPENAI_API_BASE_URL,
    RetrievalError,
    SNIPPET_MAX_LEN,
    dedup_normalized_rows,
    embed_query,
    http_json,
)

logger = logging.getLogger(__name__)


def _normalize_qdrant_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qdrant 검색 결과를 공통 포맷(rank, score, source_id 등)으로 변환한다."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        payload = row.get("payload") or {}
        text = str(payload.get("text", "") or "")
        source_id = payload.get("id", "") or str(row.get("id", ""))
        if not source_id:
            logger.warning(
                "Qdrant result missing source id (payload.id/row.id both empty): rank=%s payload_keys=%s",
                i,
                sorted(payload.keys()),
            )
        out.append(
            {
                "rank": i,
                "score": row.get("score"),
                "source_id": source_id,
                "doc_type": payload.get("doc_type", ""),
                "law_name": payload.get("law_name", ""),
                "article_no": payload.get("article_no_display", ""),
                "text": text,
                "snippet": text.replace("\n", " ")[:SNIPPET_MAX_LEN],
            }
        )
    return out


def _build_qdrant_filter(
    doc_types: list[str] | None, law_names: list[str] | None
) -> dict[str, Any] | None:
    """doc_type / law_name 필터 조건을 Qdrant payload filter 형식으로 생성한다.

    두 조건 모두 없으면 None을 반환 (필터 미적용).

    law_names는 컬렉션 종류에 관계없이 OR 조건으로 적용한다.
    - law_article: law_name 필드에서 매칭
    - legal_case / legal_relation: root_law_name, related_law_name, related_law_names 에서 매칭
    """
    # 주의:
    # - 여기서는 law_names를 "다중 필드 OR"로 표현하기 위해 should를 사용한다.
    # - 일부 Qdrant 버전/설정에서는 must + should 조합 시 should가 스코어링에만
    #   관여하는 사례가 보고되어, law_names가 필터로 강제되지 않을 수 있다.
    #   (환경에 따라 검증 필요)
    filt: dict[str, Any] = {}
    if doc_types:
        filt["must"] = [{"key": "doc_type", "match": {"any": doc_types}}]
    if law_names:
        filt["should"] = [
            {"key": "law_name", "match": {"any": law_names}},
            {"key": "root_law_name", "match": {"any": law_names}},
            {"key": "related_law_name", "match": {"any": law_names}},
            {"key": "related_law_names", "match": {"any": law_names}},
        ]
    return filt if filt else None


def search_qdrant_with_vector(
    vector: list[float],
    top_k: int,
    *,
    qdrant_url: str,
    collection: str,
    timeout: int,
    api_key: str | None = None,
    doc_types: list[str] | None = None,
    law_names: list[str] | None = None,
    dedup: bool = True,
    fetch_multiplier: int = 2,
    vector_name: str | None = None,
) -> list[dict[str, Any]]:
    """사전 계산된 벡터로 Qdrant에서 유사 문서 Top-K를 검색한다.

    임베딩을 외부에서 한 번만 계산한 뒤 여러 컬렉션을 병렬로 검색할 때 사용한다.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    if top_k <= 0:
        return []

    fetch_limit = max(1, top_k * max(1, fetch_multiplier)) if dedup else max(1, top_k)
    payload: dict[str, Any] = {
        # Qdrant named vector API:
        # - vector_name 지정 시 {"name": "...", "vector": [...]} 형태
        # - 미지정 시 기존 단일 벡터 형태([...]) 그대로 전송
        "vector": {"name": vector_name, "vector": vector} if vector_name else vector,
        "limit": fetch_limit,
        "with_payload": True,
        "with_vector": False,
    }
    filt = _build_qdrant_filter(doc_types, law_names)
    if filt:
        payload["filter"] = filt

    url = f"{qdrant_url.rstrip('/')}/collections/{urllib.parse.quote(collection)}/points/search"
    res = http_json("POST", url, payload, headers, timeout)
    if not isinstance(res, dict):
        raise RetrievalError(f"Qdrant 응답 형식 오류: dict가 아님 (type={type(res).__name__})")
    if res.get("status") == "error":
        raise RetrievalError(f"Qdrant 검색 실패 응답(status=error): {res}")
    if "result" not in res:
        raise RetrievalError(f"Qdrant 응답에 result 필드가 없습니다: {res}")
    raw_rows = res.get("result")
    if raw_rows is None:
        raw_rows = []
    if not isinstance(raw_rows, list):
        raise RetrievalError(f"Qdrant result 형식 오류: list가 아님 (type={type(raw_rows).__name__})")

    rows = _normalize_qdrant_results(raw_rows)
    if dedup:
        rows = dedup_normalized_rows(rows)

    trimmed = rows[:top_k]
    for i, row in enumerate(trimmed, start=1):
        row["rank"] = i
    return trimmed


def search_qdrant(
    query: str,
    top_k: int,
    *,
    qdrant_url: str,
    collection: str,
    timeout: int,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    embedding_api_key: str | None = None,
    embedding_api_base_url: str = DEFAULT_OPENAI_API_BASE_URL,
    embedding_dimensions: int | None = None,
    api_key: str | None = None,
    doc_types: list[str] | None = None,
    law_names: list[str] | None = None,
    dedup: bool = True,
    fetch_multiplier: int = 2,
    vector_name: str | None = None,
) -> list[dict[str, Any]]:
    """쿼리를 임베딩 후 Qdrant에서 유사 문서 Top-K를 검색한다.

    참고: 현재 API 파이프라인 경로는 `search_qdrant_with_vector()`를 주로 사용하고,
    이 함수는 임베딩+검색을 한 번에 수행하는 편의 함수 성격이 강하다.
    """
    vector = embed_query(
        query,
        embedding_model,
        api_key=embedding_api_key,
        api_base_url=embedding_api_base_url,
        dimensions=embedding_dimensions,
    )
    return search_qdrant_with_vector(
        vector, top_k,
        qdrant_url=qdrant_url,
        collection=collection,
        timeout=timeout,
        api_key=api_key,
        doc_types=doc_types,
        law_names=law_names,
        dedup=dedup,
        fetch_multiplier=fetch_multiplier,
        vector_name=vector_name,
    )
