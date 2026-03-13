#!/usr/bin/env python3
"""OpenSearch BM25 retrieval test (user-text query).

Usage examples:
1) one-shot
   python3 scripts/query_opensearch_bm25.py --question "건설업 등록 기준은?" --top-k 5

2) interactive
   python3 scripts/query_opensearch_bm25.py --interactive
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


def opensearch_auth_header(
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


def build_query(
    question: str, top_k: int, doc_types: list[str], law_names: list[str]
) -> dict[str, Any]:
    must: list[dict[str, Any]] = [
        {
            "match": {
                "text": {
                    "query": question,
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


def opensearch_search(
    *,
    opensearch_url: str,
    index_name: str,
    timeout: int,
    question: str,
    top_k: int,
    doc_types: list[str],
    law_names: list[str],
    api_key: str | None,
    username: str | None,
    password: str | None,
) -> list[dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        **opensearch_auth_header(api_key, username, password),
    }
    payload = build_query(question, top_k, doc_types, law_names)
    url = f"{opensearch_url.rstrip('/')}/{urllib.parse.quote(index_name)}/_search"
    res = http_json("POST", url, payload, headers, timeout)
    hits = (res.get("hits") or {}).get("hits") or []
    return hits if isinstance(hits, list) else []


def dedup_hits(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate results at document-level.

    Priority for dedup key:
    1) normalized source_id (remove __dupN only)
    2) explicit document identity (doc_type + doc_id / title + doc_number)
    3) source_file_path (same raw document)
    4) normalized text signature
    """
    def normalize_source_id(source_id: str) -> str:
        # Keep chunk granularity, only remove duplicate suffix.
        return re.sub(r"__dup\d+$", "", source_id)

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        src = row.get("_source") or {}
        source_id = str(src.get("id", "") or "")
        source_file_path = str(src.get("source_file_path", "") or "")
        doc_type = str(src.get("doc_type", "") or "")
        doc_id = str(src.get("doc_id", "") or "")
        title = str(src.get("title", "") or "")
        doc_number = str(src.get("doc_number", "") or "")
        norm_id = normalize_source_id(source_id)

        key = ""
        if norm_id:
            key = f"id::{norm_id}"
        elif doc_id:
            key = f"doc::{doc_type}::{doc_id}"
        elif title and doc_number:
            key = f"title_no::{doc_type}::{title}::{doc_number}"
        elif source_file_path:
            key = f"path::{source_file_path}"
        elif source_id:
            key = f"id::{source_id}"
        if not key:
            text = str(src.get("text", "") or "")
            text_norm = re.sub(r"\s+", " ", text).strip().lower()
            text_sig = hashlib.sha1(text_norm[:800].encode("utf-8")).hexdigest()
            key = f"text::{text_sig}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def normalize_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        src = row.get("_source") or {}
        text = str(src.get("text", "") or "")
        normalized.append(
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
    return normalized


def print_results(question: str, rows: list[dict[str, Any]]) -> None:
    print(f"\n[Q] {question}")
    if not rows:
        print("[INFO] 검색 결과 없음")
        return

    for row in rows:
        print(f"\n#{row['rank']} score={row['score']}")
        source_id = row.get("source_id", "")
        doc_type = row.get("doc_type", "")
        law_name = row.get("law_name", "")
        snippet = row.get("snippet", "")
        if source_id:
            print(f"source_id: {source_id}")
        if doc_type or law_name:
            print(f"meta: doc_type={doc_type} law_name={law_name}")
        if snippet:
            print(f"text: {snippet}")


def run_single_query(args: argparse.Namespace, question: str) -> int:
    opensearch_url = require_env_or_arg(
        args.opensearch_url, "OPENSEARCH_URL", "http://localhost:9200"
    )
    index_name = require_env_or_arg(args.index, "OPENSEARCH_INDEX")

    api_key = (
        args.opensearch_api_key or os.getenv("OPENSEARCH_API_KEY", "").strip() or None
    )
    username = (
        args.opensearch_username or os.getenv("OPENSEARCH_USERNAME", "").strip() or None
    )
    password = (
        args.opensearch_password or os.getenv("OPENSEARCH_PASSWORD", "").strip() or None
    )

    # Fetch more candidates so post-dedup still keeps enough unique docs.
    fetch_k = max(1, args.top_k * 5) if args.dedup else args.top_k
    rows = opensearch_search(
        opensearch_url=opensearch_url,
        index_name=index_name,
        timeout=args.timeout,
        question=question,
        top_k=fetch_k,
        doc_types=args.doc_type,
        law_names=args.law_name,
        api_key=api_key,
        username=username,
        password=password,
    )
    if args.dedup:
        rows = dedup_hits(rows)
    rows = rows[: max(1, args.top_k)]
    normalized = normalize_results(rows)

    if args.json:
        print(
            json.dumps(
                {
                    "backend": "opensearch_bm25",
                    "question": question,
                    "top_k": args.top_k,
                    "results": normalized,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_results(question, normalized)
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="User question -> OpenSearch BM25 Top-K")
    p.add_argument("--question", default="", help="질문 텍스트")
    p.add_argument("--interactive", action="store_true", help="대화형 모드")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--timeout", type=int, default=120)

    p.add_argument(
        "--opensearch-url",
        default="",
        help="기본: OPENSEARCH_URL 또는 http://localhost:9200",
    )
    p.add_argument("--index", default="", help="기본: OPENSEARCH_INDEX")
    p.add_argument("--opensearch-api-key", default="", help="기본: OPENSEARCH_API_KEY")
    p.add_argument(
        "--opensearch-username", default="", help="기본: OPENSEARCH_USERNAME"
    )
    p.add_argument(
        "--opensearch-password", default="", help="기본: OPENSEARCH_PASSWORD"
    )

    p.add_argument(
        "--doc-type", action="append", default=[], help="doc_type 필터 (복수 지정 가능)"
    )
    p.add_argument(
        "--law-name", action="append", default=[], help="law_name 필터 (복수 지정 가능)"
    )
    p.add_argument(
        "--dedup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="중복(__dupN) 결과 제거 (기본: on)",
    )
    p.add_argument("--json", action="store_true", help="원본 JSON 출력")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.interactive:
        print("OpenSearch BM25 검색 대화형 모드. 종료하려면 :q 입력")
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
