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
import json
import os
import sys

from retrieval_common import require_env_or_arg, search_bm25


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

    rows = search_bm25(
        question,
        args.top_k,
        opensearch_url=opensearch_url,
        index_name=index_name,
        timeout=args.timeout,
        api_key=api_key,
        username=username,
        password=password,
        doc_types=args.doc_type,
        law_names=args.law_name,
        dedup=args.dedup,
        fetch_multiplier=5,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "backend": "opensearch_bm25",
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
