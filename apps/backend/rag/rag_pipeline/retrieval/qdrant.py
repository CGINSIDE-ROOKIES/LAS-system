"""Qdrant 벡터 검색 서비스."""

from __future__ import annotations

import urllib.parse
from typing import Any

from .common import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_OPENAI_API_BASE_URL,
    SNIPPET_MAX_LEN,
    dedup_normalized_rows,
    embed_query,
    http_json,
)


def _normalize_qdrant_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qdrant 검색 결과를 공통 포맷(rank, score, source_id 등)으로 변환한다."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        payload = row.get("payload") or {}
        text = str(payload.get("text", "") or "")
        out.append(
            {
                "rank": i,
                "score": row.get("score"),
                "source_id": payload.get("id", "") or str(row.get("id", "")),
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
    must: list[dict[str, Any]] = []
    if doc_types:
        must.append({"key": "doc_type", "match": {"any": doc_types}})
    if law_names:
        must.append({
            "should": [
                {"key": "law_name", "match": {"any": law_names}},
                {"key": "root_law_name", "match": {"any": law_names}},
                {"key": "related_law_name", "match": {"any": law_names}},
                {"key": "related_law_names", "match": {"any": law_names}},
            ]
        })
    return {"must": must} if must else None


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

    fetch_limit = max(1, top_k * max(1, fetch_multiplier)) if dedup else max(1, top_k)
    payload: dict[str, Any] = {
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
    raw_rows = res.get("result", [])
    if not isinstance(raw_rows, list):
        return []

    rows = _normalize_qdrant_results(raw_rows)
    if dedup:
        rows = dedup_normalized_rows(rows)

    trimmed = rows[: max(1, top_k)]
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
    embedding_provider: str = "sentence_transformers",
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
    """쿼리를 임베딩 후 Qdrant에서 유사 문서 Top-K를 검색한다."""
    vector = embed_query(
        query,
        embedding_model,
        provider=embedding_provider,
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
