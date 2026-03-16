#!/usr/bin/env python3
"""Qdrant dense retrieval test (user-text query).

Usage examples:
1) one-shot
   uv run python scripts/query_qdrant_topk.py --question "건설업 등록 기준은?" --top-k 5

2) interactive
   python3 scripts/query_qdrant_topk.py --interactive
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from retrieval_common import (
    DEFAULT_EMBEDDING_MODEL,
    require_env_or_arg,
    search_qdrant,
)


def print_results(question: str, rows: list[dict[str, object]]) -> None:
    print(f"\n[Q] {question}")
    if not rows:
        print("[INFO] 검색 결과 없음")
        return

    for row in rows:
        print(f"\n#{row['rank']} score={row['score']}")
        source_id = str(row.get("source_id", "") or "")
        doc_type = str(row.get("doc_type", "") or "")
        law_name = str(row.get("law_name", "") or "")
        snippet = str(row.get("snippet", "") or "")
        if source_id:
            print(f"source_id: {source_id}")
        if doc_type or law_name:
            print(f"meta: doc_type={doc_type} law_name={law_name}")
        if snippet:
            print(f"text: {snippet}")


def run_single_query(args: argparse.Namespace, question: str) -> int:
    qdrant_url = require_env_or_arg(
        args.qdrant_url, "QDRANT_URL", "http://localhost:6333"
    )
    collection = require_env_or_arg(args.collection, "QDRANT_COLLECTION")
    model_name = require_env_or_arg(
        args.embedding_model, "EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
    )
    api_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY", "").strip() or None

    rows = search_qdrant(
        question,
        args.top_k,
        qdrant_url=qdrant_url,
        collection=collection,
        timeout=args.timeout,
        embedding_model=model_name,
        api_key=api_key,
        doc_types=args.doc_type or None,
        law_names=args.law_name or None,
        dedup=True,
        fetch_multiplier=2,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "backend": "qdrant",
                    "question": question,
                    "top_k": args.top_k,
                    "results": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_results(question, rows)
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="User question -> Qdrant Top-K")
    p.add_argument("--question", default="", help="질문 텍스트")
    p.add_argument("--interactive", action="store_true", help="대화형 모드")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument(
        "--qdrant-url", default="", help="기본: QDRANT_URL 또는 http://localhost:6333"
    )
    p.add_argument("--collection", default="", help="기본: QDRANT_COLLECTION")
    p.add_argument("--qdrant-api-key", default="", help="기본: QDRANT_API_KEY")
    p.add_argument(
        "--embedding-model", default="", help=f"기본: {DEFAULT_EMBEDDING_MODEL}"
    )
    p.add_argument(
        "--doc-type",
        action="append",
        default=[],
        help="payload.doc_type 필터 (복수 지정 가능)",
    )
    p.add_argument(
        "--law-name",
        action="append",
        default=[],
        help="payload.law_name 필터 (복수 지정 가능)",
    )
    p.add_argument("--json", action="store_true", help="원본 JSON 출력")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.interactive:
        print("Qdrant 검색 대화형 모드. 종료하려면 :q 입력")
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
