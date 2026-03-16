from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_MODEL_CACHE: dict[str, Any] = {}


def require_env_or_arg(
    value: str | None, env_name: str, fallback: str | None = None
) -> str:
    if value and value.strip():
        return value.strip()
    env_val = os.getenv(env_name, "").strip()
    if env_val:
        return env_val
    if fallback is not None:
        return fallback
    raise SystemExit(
        f"Missing required setting: --{env_name.lower().replace('_', '-')} or {env_name}"
    )


def http_json(
    method: str,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    req = urllib.request.Request(
        url=url,
        method=method,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {method} {url}\n{body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Network error {method} {url}: {exc}") from exc


def embed_query(text: str, model_name: str) -> list[float]:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover
        raise SystemExit(
            "sentence-transformers가 필요합니다.\n"
            "설치: uv add sentence-transformers 또는 pip install sentence-transformers"
        ) from exc

    model = _MODEL_CACHE.get(model_name)
    if model is None:
        model = SentenceTransformer(model_name)
        _MODEL_CACHE[model_name] = model

    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist() if hasattr(vec, "tolist") else list(vec)


def normalize_source_id(source_id: str) -> str:
    if not source_id:
        return ""
    return re.sub(r"__dup\d+$", "", source_id)


def _fallback_text_key(text: str) -> str:
    text_norm = re.sub(r"\s+", " ", text).strip().lower()
    digest = hashlib.sha1(text_norm[:800].encode("utf-8")).hexdigest()
    return f"text::{digest}"


def dedup_normalized_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        sid = str(row.get("source_id", "") or "")
        key = normalize_source_id(sid) if sid else ""
        if not key:
            key = _fallback_text_key(str(row.get("text", "") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _normalize_qdrant_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        payload = row.get("payload") or {}
        text = str(payload.get("text", "") or "")
        out.append(
            {
                "rank": i,
                "score": row.get("score"),
                "source_id": payload.get("source_id", ""),
                "doc_type": payload.get("doc_type", ""),
                "law_name": payload.get("law_name", ""),
                "text": text,
                "snippet": text.replace("\n", " ")[:180],
            }
        )
    return out


def _normalize_bm25_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                "text": text,
                "snippet": text.replace("\n", " ")[:180],
            }
        )
    return out


def _build_qdrant_filter(
    doc_types: list[str] | None, law_names: list[str] | None
) -> dict[str, Any] | None:
    must: list[dict[str, Any]] = []
    if doc_types:
        must.append({"key": "doc_type", "match": {"any": doc_types}})
    if law_names:
        must.append({"key": "law_name", "match": {"any": law_names}})
    return {"must": must} if must else None


def search_qdrant(
    query: str,
    top_k: int,
    *,
    qdrant_url: str,
    collection: str,
    timeout: int,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    api_key: str | None = None,
    doc_types: list[str] | None = None,
    law_names: list[str] | None = None,
    dedup: bool = True,
    fetch_multiplier: int = 2,
) -> list[dict[str, Any]]:
    vector = embed_query(query, embedding_model)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    fetch_limit = max(1, top_k * max(1, fetch_multiplier)) if dedup else max(1, top_k)
    payload: dict[str, Any] = {
        "vector": vector,
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


def _opensearch_auth_header(
    api_key: str | None, username: str | None, password: str | None
) -> dict[str, str]:
    if api_key:
        return {"Authorization": f"ApiKey {api_key}"}
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
            "ascii"
        )
        return {"Authorization": f"Basic {token}"}
    return {}


def _build_bm25_query(
    query: str, top_k: int, doc_types: list[str] | None, law_names: list[str] | None
) -> dict[str, Any]:
    must: list[dict[str, Any]] = [
        {
            "match": {
                "text": {
                    "query": query,
                    "operator": "or",
                }
            }
        }
    ]
    filters: list[dict[str, Any]] = []

    if doc_types:
        filters.append({"terms": {"doc_type.keyword": doc_types}})
    if law_names:
        filters.append({"terms": {"law_name.keyword": law_names}})

    query_obj: dict[str, Any] = {"bool": {"must": must}}
    if filters:
        query_obj["bool"]["filter"] = filters

    return {
        "size": max(1, top_k),
        "query": query_obj,
        "_source": True,
    }


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
