"""OpenSearch BM25 키워드 검색 서비스."""

from __future__ import annotations

import base64
import urllib.parse
from typing import Any

from .common import SNIPPET_MAX_LEN, dedup_normalized_rows, http_json


def _opensearch_auth_header(
    api_key: str | None, username: str | None, password: str | None
) -> dict[str, str]:
    """API 키 > Basic 인증 > 인증 없음 순으로 Authorization 헤더를 반환한다."""
    if api_key:
        return {"Authorization": f"ApiKey {api_key}"}
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}
    return {}


def _normalize_bm25_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenSearch BM25 검색 결과를 공통 포맷으로 변환한다."""
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        src = row.get("_source") or {}
        text = str(src.get("text", "") or "")
        out.append(
            {
                "rank": i,
                "score": row.get("_score"),
                "source_id": src.get("id", ""),
                "doc_type": src.get("doc_type", ""),
                "law_name": src.get("law_name", ""),
                "article_no": src.get("article_no_display", ""),
                "text": text,
                "snippet": text.replace("\n", " ")[:SNIPPET_MAX_LEN],
            }
        )
    return out


def _build_bm25_query(
    query: str, top_k: int, doc_types: list[str] | None, law_names: list[str] | None
) -> dict[str, Any]:
    """OpenSearch BM25 검색용 쿼리 DSL을 생성한다.

    `search_text` 필드(법령명+조문번호+본문 통합)에 OR 매칭을 적용하고, doc_type / law_name 조건은 filter로 추가한다.
    """
    must: list[dict[str, Any]] = [
        {"match": {"search_text": {"query": query, "operator": "or"}}}
    ]
    filters: list[dict[str, Any]] = []

    if doc_types:
        filters.append({"terms": {"doc_type": doc_types}})
    if law_names:
        filters.append({
            "bool": {
                "should": [
                    {"terms": {"law_name": law_names}},
                    {"terms": {"root_law_name": law_names}},
                    {"terms": {"related_law_name": law_names}},
                    {"terms": {"related_law_names": law_names}},
                ],
                "minimum_should_match": 1,
            }
        })

    query_obj: dict[str, Any] = {"bool": {"must": must}}
    if filters:
        query_obj["bool"]["filter"] = filters

    return {"size": max(1, top_k), "query": query_obj, "_source": True}


def search_bm25(
    query: str,
    top_k: int,
    *,
    opensearch_url: str,
    index_name: str,
    timeout: int,
    api_key: str | None = None,
    username: str | None = None,
    password: str | None = None,
    doc_types: list[str] | None = None,
    law_names: list[str] | None = None,
    dedup: bool = True,
    fetch_multiplier: int = 5,
) -> list[dict[str, Any]]:
    """OpenSearch에서 BM25 키워드 검색으로 Top-K 문서를 반환한다.

    search_qdrant와 동일한 공통 포맷으로 결과를 반환하므로 두 결과를 병합하기 쉽다.
    """
    headers = {
        "Content-Type": "application/json",
        **_opensearch_auth_header(api_key, username, password),
    }

    fetch_k = max(1, top_k * max(1, fetch_multiplier)) if dedup else max(1, top_k)
    payload = _build_bm25_query(query, fetch_k, doc_types, law_names)

    url = f"{opensearch_url.rstrip('/')}/{urllib.parse.quote(index_name)}/_search"
    res = http_json("POST", url, payload, headers, timeout)
    hits = (res.get("hits") or {}).get("hits") or []
    if not isinstance(hits, list):
        return []

    rows = _normalize_bm25_results(hits)
    if dedup:
        rows = dedup_normalized_rows(rows)

    trimmed = rows[: max(1, top_k)]
    for i, row in enumerate(trimmed, start=1):
        row["rank"] = i
    return trimmed
