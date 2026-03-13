#!/usr/bin/env python3
"""Hybrid retrieval (Qdrant + OpenSearch BM25) with RRF fusion.

Usage examples:
  uv run python scripts/query_hybrid_rrf.py --question "건설업 등록 기준은?" --top-k 5
  uv run python scripts/query_hybrid_rrf.py --interactive --top-k 5
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def require_env_or_arg(value: str | None, env_name: str, fallback: str | None = None) -> str:
    if value and value.strip():
        return value.strip()
    env_val = os.getenv(env_name, "").strip()
    if env_val:
        return env_val
    if fallback is not None:
        return fallback
    raise SystemExit(f"Missing required setting: --{env_name.lower().replace('_', '-')} or {env_name}")


def http_json(method: str, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
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

    model = SentenceTransformer(model_name)
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist() if hasattr(vec, "tolist") else list(vec)


def build_qdrant_filter(doc_types: list[str], law_names: list[str]) -> dict[str, Any] | None:
    must: list[dict[str, Any]] = []
    if doc_types:
        must.append({"key": "doc_type", "match": {"any": doc_types}})
    if law_names:
        must.append({"key": "law_name", "match": {"any": law_names}})
    return {"must": must} if must else None


def qdrant_search(
    *,
    qdrant_url: str,
    collection: str,
    api_key: str | None,
    vector: list[float],
    top_k: int,
    timeout: int,
    doc_types: list[str],
    law_names: list[str],
) -> list[dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    payload: dict[str, Any] = {
        "vector": vector,
        "limit": max(1, top_k),
        "with_payload": True,
        "with_vector": False,
    }
    filt = build_qdrant_filter(doc_types, law_names)
    if filt:
        payload["filter"] = filt

    url = f"{qdrant_url.rstrip('/')}/collections/{urllib.parse.quote(collection)}/points/search"
    res = http_json("POST", url, payload, headers, timeout)
    rows = res.get("result", [])
    if not isinstance(rows, list):
        return []

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


def opensearch_auth_header(api_key: str | None, username: str | None, password: str | None) -> dict[str, str]:
    if api_key:
        return {"Authorization": f"ApiKey {api_key}"}
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}
    return {}


def build_os_query(question: str, top_k: int, doc_types: list[str], law_names: list[str]) -> dict[str, Any]:
    must: list[dict[str, Any]] = [{"match": {"text": {"query": question, "operator": "or"}}}]
    filters: list[dict[str, Any]] = []
    if doc_types:
        filters.append({"terms": {"doc_type.keyword": doc_types}})
    if law_names:
        filters.append({"terms": {"law_name.keyword": law_names}})

    query_obj: dict[str, Any] = {"bool": {"must": must}}
    if filters:
        query_obj["bool"]["filter"] = filters

    return {"size": max(1, top_k), "query": query_obj, "_source": True}


def opensearch_search(
    *,
    opensearch_url: str,
    index_name: str,
    api_key: str | None,
    username: str | None,
    password: str | None,
    question: str,
    top_k: int,
    timeout: int,
    doc_types: list[str],
    law_names: list[str],
) -> list[dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        **opensearch_auth_header(api_key, username, password),
    }
    payload = build_os_query(question, top_k, doc_types, law_names)
    url = f"{opensearch_url.rstrip('/')}/{urllib.parse.quote(index_name)}/_search"
    res = http_json("POST", url, payload, headers, timeout)
    rows = ((res.get("hits") or {}).get("hits") or [])
    if not isinstance(rows, list):
        return []

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


def normalize_sid(source_id: str) -> str:
    if not source_id:
        return ""
    return re.sub(r"__dup\d+$", "", source_id)


def fuse_rrf(
    qdrant_rows: list[dict[str, Any]],
    os_rows: list[dict[str, Any]],
    *,
    rrf_k: int,
    top_k: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    def add_rows(rows: list[dict[str, Any]], backend: str) -> None:
        for row in rows:
            rank = int(row.get("rank", 0) or 0)
            if rank <= 0:
                continue
            sid = str(row.get("source_id", "") or "")
            key = normalize_sid(sid) if sid else ""
            if not key:
                # fallback on text hash for rows without source id
                text = str(row.get("text", "") or "")
                key = f"text::{hashlib.sha1(text[:800].encode('utf-8')).hexdigest()}"

            rrf_score = 1.0 / (rrf_k + rank)
            cur = merged.get(key)
            if cur is None:
                cur = {
                    "source_id": sid,
                    "doc_type": row.get("doc_type", ""),
                    "law_name": row.get("law_name", ""),
                    "text": row.get("text", ""),
                    "snippet": row.get("snippet", ""),
                    "rrf_score": 0.0,
                    "sources": [],
                }
                merged[key] = cur

            cur["rrf_score"] += rrf_score
            cur["sources"].append({"backend": backend, "rank": rank, "score": row.get("score")})

    add_rows(qdrant_rows, "qdrant")
    add_rows(os_rows, "opensearch_bm25")

    ranked = sorted(merged.values(), key=lambda x: x["rrf_score"], reverse=True)

    out: list[dict[str, Any]] = []
    for i, row in enumerate(ranked[: max(1, top_k)], start=1):
        out.append(
            {
                "rank": i,
                "score": row["rrf_score"],
                "source_id": row.get("source_id", ""),
                "doc_type": row.get("doc_type", ""),
                "law_name": row.get("law_name", ""),
                "text": row.get("text", ""),
                "snippet": row.get("snippet", ""),
                "sources": row.get("sources", []),
            }
        )
    return out


def print_results(question: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n[Q] {question}")
    if not rows:
        print("[INFO] 검색 결과 없음")
        return

    for row in rows:
        print(f"\n#{row['rank']} score={row['score']}")
        sid = row.get("source_id", "")
        if sid:
            print(f"source_id: {sid}")
        dt = row.get("doc_type", "")
        ln = row.get("law_name", "")
        if dt or ln:
            print(f"meta: doc_type={dt} law_name={ln}")
        snip = row.get("snippet", "")
        if snip:
            print(f"text: {snip}")


def run_single_query(args: argparse.Namespace, question: str) -> int:
    qdrant_url = require_env_or_arg(args.qdrant_url, "QDRANT_URL", "http://localhost:6333")
    qdrant_collection = require_env_or_arg(args.qdrant_collection, "QDRANT_COLLECTION")
    qdrant_api_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY", "").strip() or None

    opensearch_url = require_env_or_arg(args.opensearch_url, "OPENSEARCH_URL", "http://localhost:9200")
    opensearch_index = require_env_or_arg(args.opensearch_index, "OPENSEARCH_INDEX")
    os_api_key = args.opensearch_api_key or os.getenv("OPENSEARCH_API_KEY", "").strip() or None
    os_user = args.opensearch_username or os.getenv("OPENSEARCH_USERNAME", "").strip() or None
    os_pass = args.opensearch_password or os.getenv("OPENSEARCH_PASSWORD", "").strip() or None

    model_name = require_env_or_arg(args.embedding_model, "EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)

    # Pull extra candidates per backend before fusion.
    candidate_k = max(args.top_k, args.candidate_k)

    vector = embed_query(question, model_name)
    qdrant_rows = qdrant_search(
        qdrant_url=qdrant_url,
        collection=qdrant_collection,
        api_key=qdrant_api_key,
        vector=vector,
        top_k=candidate_k,
        timeout=args.timeout,
        doc_types=args.doc_type,
        law_names=args.law_name,
    )
    os_rows = opensearch_search(
        opensearch_url=opensearch_url,
        index_name=opensearch_index,
        api_key=os_api_key,
        username=os_user,
        password=os_pass,
        question=question,
        top_k=candidate_k,
        timeout=args.timeout,
        doc_types=args.doc_type,
        law_names=args.law_name,
    )

    fused = fuse_rrf(qdrant_rows, os_rows, rrf_k=args.rrf_k, top_k=args.top_k)

    if args.json:
        print(
            json.dumps(
                {
                    "backend": "hybrid_rrf",
                    "question": question,
                    "top_k": args.top_k,
                    "rrf_k": args.rrf_k,
                    "candidates": {
                        "qdrant": len(qdrant_rows),
                        "opensearch_bm25": len(os_rows),
                    },
                    "results": fused,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_results(question, fused)
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="User question -> Hybrid RRF Top-K")
    p.add_argument("--question", default="", help="질문 텍스트")
    p.add_argument("--interactive", action="store_true", help="대화형 모드")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--candidate-k", type=int, default=30, help="백엔드별 후보 수")
    p.add_argument("--rrf-k", type=int, default=60, help="RRF k constant")
    p.add_argument("--timeout", type=int, default=120)

    p.add_argument("--qdrant-url", default="", help="기본: QDRANT_URL")
    p.add_argument("--qdrant-collection", default="", help="기본: QDRANT_COLLECTION")
    p.add_argument("--qdrant-api-key", default="", help="기본: QDRANT_API_KEY")

    p.add_argument("--opensearch-url", default="", help="기본: OPENSEARCH_URL")
    p.add_argument("--opensearch-index", default="", help="기본: OPENSEARCH_INDEX")
    p.add_argument("--opensearch-api-key", default="", help="기본: OPENSEARCH_API_KEY")
    p.add_argument("--opensearch-username", default="", help="기본: OPENSEARCH_USERNAME")
    p.add_argument("--opensearch-password", default="", help="기본: OPENSEARCH_PASSWORD")

    p.add_argument("--embedding-model", default="", help=f"기본: {DEFAULT_EMBEDDING_MODEL}")
    p.add_argument("--doc-type", action="append", default=[], help="doc_type 필터 (복수 지정 가능)")
    p.add_argument("--law-name", action="append", default=[], help="law_name 필터 (복수 지정 가능)")
    p.add_argument("--json", action="store_true", help="원본 JSON 출력")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.interactive:
        print("Hybrid RRF 검색 대화형 모드. 종료하려면 :q 입력")
        while True:
            try:
                q = input("\n질문> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not q:
                continue
            if q in {":q", "quit", "exit"}:
                return 0
            run_single_query(args, q)

    if not args.question.strip():
        raise SystemExit("--question 또는 --interactive 중 하나는 필요합니다.")

    return run_single_query(args, args.question.strip())


if __name__ == "__main__":
    sys.exit(main())
