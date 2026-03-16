#!/usr/bin/env python3
"""Hybrid retrieval (Qdrant + OpenSearch BM25) with RRF fusion.

Usage examples:
  uv run python scripts/query_hybrid_rrf.py --question "건설업 등록 기준은?" --top-k 5
  uv run python scripts/query_hybrid_rrf.py --interactive --top-k 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from retrieval_common import (
    DEFAULT_EMBEDDING_MODEL,
    normalize_source_id,
    require_env_or_arg,
    search_bm25,
    search_qdrant,
)


def _rrf_key(row: dict[str, object]) -> str:
    sid = str(row.get("source_id", "") or "")
    key = normalize_source_id(sid) if sid else ""
    if key:
        return key
    text = str(row.get("text", "") or "")
    return f"text::{hashlib.sha1(text[:800].encode('utf-8')).hexdigest()}"


def _dedup_backend_rows_for_rrf(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep only the highest-ranked item per document key in a single backend."""
    best_by_key: dict[str, dict[str, object]] = {}
    best_rank_by_key: dict[str, int] = {}

    for row in rows:
        rank = int(row.get("rank", 0) or 0)
        if rank <= 0:
            continue
        key = _rrf_key(row)
        prev_rank = best_rank_by_key.get(key)
        if prev_rank is None or rank < prev_rank:
            best_rank_by_key[key] = rank
            best_by_key[key] = row

    return sorted(best_by_key.values(), key=lambda r: int(r.get("rank", 0) or 0))


def fuse_rrf(
    qdrant_rows: list[dict[str, object]],
    os_rows: list[dict[str, object]],
    *,
    rrf_k: int,
    top_k: int,
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}

    def add_rows(rows: list[dict[str, object]], backend: str) -> None:
        deduped_rows = _dedup_backend_rows_for_rrf(rows)
        for row in deduped_rows:
            rank = int(row.get("rank", 0) or 0)
            if rank <= 0:
                continue

            sid = str(row.get("source_id", "") or "")
            key = _rrf_key(row)

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

            cur["rrf_score"] = float(cur["rrf_score"]) + rrf_score
            cast_sources = cur["sources"]
            if isinstance(cast_sources, list):
                cast_sources.append(
                    {"backend": backend, "rank": rank, "score": row.get("score")}
                )

    add_rows(qdrant_rows, "qdrant")
    add_rows(os_rows, "opensearch_bm25")

    ranked = sorted(merged.values(), key=lambda x: float(x["rrf_score"]), reverse=True)

    out: list[dict[str, object]] = []
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


def print_results(question: str, rows: list[dict[str, object]]) -> None:
    print(f"\n[Q] {question}")
    if not rows:
        print("[INFO] 검색 결과 없음")
        return

    for row in rows:
        print(f"\n#{row['rank']} score={row['score']}")
        sid = str(row.get("source_id", "") or "")
        if sid:
            print(f"source_id: {sid}")
        doc_type = str(row.get("doc_type", "") or "")
        law_name = str(row.get("law_name", "") or "")
        if doc_type or law_name:
            print(f"meta: doc_type={doc_type} law_name={law_name}")
        snippet = str(row.get("snippet", "") or "")
        if snippet:
            print(f"text: {snippet}")


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

    candidate_k = max(args.top_k, args.candidate_k)

    qdrant_rows = search_qdrant(
        question,
        candidate_k,
        qdrant_url=qdrant_url,
        collection=qdrant_collection,
        timeout=args.timeout,
        embedding_model=model_name,
        api_key=qdrant_api_key,
        doc_types=args.doc_type,
        law_names=args.law_name,
        dedup=True,
        fetch_multiplier=2,
    )
    os_rows = search_bm25(
        question,
        candidate_k,
        opensearch_url=opensearch_url,
        index_name=opensearch_index,
        timeout=args.timeout,
        api_key=os_api_key,
        username=os_user,
        password=os_pass,
        doc_types=args.doc_type,
        law_names=args.law_name,
        dedup=True,
        fetch_multiplier=5,
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
