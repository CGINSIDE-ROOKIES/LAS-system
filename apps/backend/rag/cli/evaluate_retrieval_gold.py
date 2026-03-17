#!/usr/bin/env python3
"""Evaluate retrieval quality against gold evaluation CSV.

Usage:
  uv run python scripts/evaluate_retrieval_gold.py --top-k 5
  uv run python scripts/evaluate_retrieval_gold.py --backend hybrid --top-k 5
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from apps.backend.rag.cli.query_hybrid_rrf import fuse_rrf
from apps.backend.rag.cli.retrieval_common import (
    DEFAULT_EMBEDDING_MODEL,
    require_env_or_arg,
    search_bm25,
    search_qdrant,
)


@dataclass
class GoldRow:
    query: str
    intent: str
    gold_law: str
    gold_article: str
    expected_doc_type: str
    notes: str


@dataclass
class EvalRow:
    backend: str
    query: str
    intent: str
    expected_doc_type: str
    gold_law: str
    gold_article: str
    hit: bool
    top1_source_id: str
    top1_doc_type: str
    top1_law_name: str
    top1_score: str


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent
    default_dataset = base_dir / "data/staging/eval_set.csv"
    if not default_dataset.exists():
        legacy_candidates = [
            script_dir / "retrieval_dataset_gold.csv",
            script_dir / "eval_set.csv",
        ]
        for cand in legacy_candidates:
            if cand.exists():
                default_dataset = cand
                break

    p = argparse.ArgumentParser(description="Evaluate retrieval against gold CSV")
    p.add_argument(
        "--dataset",
        default=str(default_dataset),
        help="gold CSV path",
    )
    p.add_argument(
        "--backend",
        choices=["all", "qdrant", "bm25", "hybrid"],
        default="all",
        help="evaluation backend",
    )
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--candidate-k", type=int, default=30)
    p.add_argument("--rrf-k", type=int, default=60)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--max-misses", type=int, default=10)
    p.add_argument(
        "--out-csv", default="", help="query-level evaluation result CSV output path"
    )

    p.add_argument("--qdrant-url", default="", help="기본: QDRANT_URL")
    p.add_argument("--qdrant-collection", default="", help="기본: QDRANT_COLLECTION")
    p.add_argument("--qdrant-api-key", default="", help="기본: QDRANT_API_KEY")

    p.add_argument("--opensearch-url", default="", help="기본: OPENSEARCH_URL")
    p.add_argument("--opensearch-index", default="", help="기본: OPENSEARCH_INDEX")
    p.add_argument("--opensearch-api-key", default="", help="기본: OPENSEARCH_API_KEY")
    p.add_argument(
        "--opensearch-username", default="", help="기본: OPENSEARCH_USERNAME"
    )
    p.add_argument(
        "--opensearch-password", default="", help="기본: OPENSEARCH_PASSWORD"
    )

    p.add_argument(
        "--embedding-model", default="", help=f"기본: {DEFAULT_EMBEDDING_MODEL}"
    )
    return p.parse_args()


def load_gold(path: Path) -> list[GoldRow]:
    rows: list[GoldRow] = []
    with path.open("r", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for row in rd:
            rows.append(
                GoldRow(
                    query=(row.get("query") or "").strip(),
                    intent=(row.get("intent") or "").strip(),
                    gold_law=(row.get("gold_law") or "").strip(),
                    gold_article=(row.get("gold_article") or "").strip(),
                    expected_doc_type=(row.get("expected_doc_type") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return rows


def resolve_dataset_path(dataset_arg: str) -> Path:
    p = Path(dataset_arg)
    if p.exists():
        return p

    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent

    # Fallback 1: relative to project base directory.
    alt0 = (base_dir / dataset_arg).resolve()
    if alt0.exists():
        return alt0

    # Fallback 2: relative to this script directory.
    alt1 = (script_dir / dataset_arg).resolve()
    if alt1.exists():
        return alt1

    # Fallback 3: if user passed "scripts/xxx.csv", strip the leading scripts/.
    parts = list(p.parts)
    if parts and parts[0] == "scripts":
        alt2 = (script_dir / Path(*parts[1:])).resolve()
        if alt2.exists():
            return alt2

    return p


def parse_allowed_doc_types(notes: str) -> set[str]:
    prefix = "allowed_doc_types="
    if not notes.startswith(prefix):
        return {"law", "prec", "decc", "expc"}
    raw = notes[len(prefix) :]
    return {x.strip() for x in raw.split("|") if x.strip()}


def row_hit(row: GoldRow, results: list[dict[str, object]]) -> bool:
    expected = row.expected_doc_type
    if expected == "law":
        for r in results:
            doc_type = str(r.get("doc_type", "") or "")
            law_name = str(r.get("law_name", "") or "")
            text = str(r.get("text", "") or "")
            law_ok = doc_type == "law" or (
                row.gold_law and row.gold_law in (law_name + text)
            )
            article_ok = True if not row.gold_article else row.gold_article in text
            if law_ok and article_ok:
                return True
        return False

    if expected in {"prec", "decc", "expc"}:
        return any(str(r.get("doc_type", "") or "") == expected for r in results)

    if expected == "mixed":
        allowed = parse_allowed_doc_types(row.notes)
        return any(str(r.get("doc_type", "") or "") in allowed for r in results)

    return False


def eval_backend(
    backend: str,
    rows: list[GoldRow],
    args: argparse.Namespace,
) -> tuple[
    dict[str, int],
    dict[str, dict[str, int]],
    list[tuple[GoldRow, list[dict[str, object]]]],
    list[EvalRow],
]:
    qdrant_url = require_env_or_arg(
        args.qdrant_url, "QDRANT_URL", "http://localhost:6333"
    )
    qdrant_collection = require_env_or_arg(args.qdrant_collection, "QDRANT_COLLECTION")
    qdrant_api_key = (
        args.qdrant_api_key or os.getenv("QDRANT_API_KEY", "").strip() or None
    )

    opensearch_url = require_env_or_arg(
        args.opensearch_url, "OPENSEARCH_URL", "http://localhost:9200"
    )
    opensearch_index = require_env_or_arg(args.opensearch_index, "OPENSEARCH_INDEX")
    os_api_key = (
        args.opensearch_api_key or os.getenv("OPENSEARCH_API_KEY", "").strip() or None
    )
    os_user = (
        args.opensearch_username or os.getenv("OPENSEARCH_USERNAME", "").strip() or None
    )
    os_pass = (
        args.opensearch_password or os.getenv("OPENSEARCH_PASSWORD", "").strip() or None
    )

    model_name = require_env_or_arg(
        args.embedding_model, "EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
    )

    total = {"count": 0, "hit": 0}
    by_intent: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "hit": 0})
    misses: list[tuple[GoldRow, list[dict[str, object]]]] = []
    eval_rows: list[EvalRow] = []

    for row in rows:
        if not row.query:
            continue
        total["count"] += 1
        by_intent[row.intent]["count"] += 1

        if backend == "qdrant":
            res = search_qdrant(
                row.query,
                args.top_k,
                qdrant_url=qdrant_url,
                collection=qdrant_collection,
                timeout=args.timeout,
                embedding_model=model_name,
                api_key=qdrant_api_key,
                dedup=True,
                fetch_multiplier=2,
            )
        elif backend == "bm25":
            res = search_bm25(
                row.query,
                args.top_k,
                opensearch_url=opensearch_url,
                index_name=opensearch_index,
                timeout=args.timeout,
                api_key=os_api_key,
                username=os_user,
                password=os_pass,
                dedup=True,
                fetch_multiplier=5,
            )
        else:
            qdrant_rows = search_qdrant(
                row.query,
                max(args.top_k, args.candidate_k),
                qdrant_url=qdrant_url,
                collection=qdrant_collection,
                timeout=args.timeout,
                embedding_model=model_name,
                api_key=qdrant_api_key,
                dedup=True,
                fetch_multiplier=2,
            )
            bm25_rows = search_bm25(
                row.query,
                max(args.top_k, args.candidate_k),
                opensearch_url=opensearch_url,
                index_name=opensearch_index,
                timeout=args.timeout,
                api_key=os_api_key,
                username=os_user,
                password=os_pass,
                dedup=True,
                fetch_multiplier=5,
            )
            res = fuse_rrf(qdrant_rows, bm25_rows, rrf_k=args.rrf_k, top_k=args.top_k)

        hit = row_hit(row, res)
        if hit:
            total["hit"] += 1
            by_intent[row.intent]["hit"] += 1
        else:
            misses.append((row, res))
        top1 = res[0] if res else {}
        eval_rows.append(
            EvalRow(
                backend=backend,
                query=row.query,
                intent=row.intent,
                expected_doc_type=row.expected_doc_type,
                gold_law=row.gold_law,
                gold_article=row.gold_article,
                hit=hit,
                top1_source_id=str(top1.get("source_id", "") or ""),
                top1_doc_type=str(top1.get("doc_type", "") or ""),
                top1_law_name=str(top1.get("law_name", "") or ""),
                top1_score=str(top1.get("score", "") or ""),
            )
        )

    return total, by_intent, misses, eval_rows


def print_report(
    backend: str, total: dict[str, int], by_intent: dict[str, dict[str, int]]
) -> None:
    count = total["count"]
    hit = total["hit"]
    ratio = (hit / count) if count else 0.0
    print(f"\n=== {backend} ===")
    print(f"Hit@k: {hit}/{count} ({ratio:.3f})")
    for intent in sorted(by_intent.keys()):
        c = by_intent[intent]["count"]
        h = by_intent[intent]["hit"]
        r = (h / c) if c else 0.0
        print(f"  - {intent}: {h}/{c} ({r:.3f})")


def write_out_csv(path: Path, rows: list[EvalRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(
            f,
            fieldnames=[
                "backend",
                "query",
                "intent",
                "expected_doc_type",
                "gold_law",
                "gold_article",
                "hit",
                "top1_source_id",
                "top1_doc_type",
                "top1_law_name",
                "top1_score",
            ],
        )
        wr.writeheader()
        for row in rows:
            wr.writerow(
                {
                    "backend": row.backend,
                    "query": row.query,
                    "intent": row.intent,
                    "expected_doc_type": row.expected_doc_type,
                    "gold_law": row.gold_law,
                    "gold_article": row.gold_article,
                    "hit": "1" if row.hit else "0",
                    "top1_source_id": row.top1_source_id,
                    "top1_doc_type": row.top1_doc_type,
                    "top1_law_name": row.top1_law_name,
                    "top1_score": row.top1_score,
                }
            )


def main() -> int:
    args = parse_args()
    dataset_path = resolve_dataset_path(args.dataset)
    rows = load_gold(dataset_path)
    if not rows:
        raise SystemExit(f"No rows in dataset: {dataset_path}")

    backends = ["qdrant", "bm25", "hybrid"] if args.backend == "all" else [args.backend]
    all_eval_rows: list[EvalRow] = []
    for backend in backends:
        total, by_intent, misses, eval_rows = eval_backend(backend, rows, args)
        all_eval_rows.extend(eval_rows)
        print_report(backend, total, by_intent)
        if misses:
            print(f"  misses (up to {args.max_misses}):")
            for row, res in misses[: max(0, args.max_misses)]:
                top_sid = str(res[0].get("source_id", "")) if res else "(none)"
                top_type = str(res[0].get("doc_type", "")) if res else "(none)"
                print(
                    f"    * [{row.intent}] {row.query} -> top1={top_sid} ({top_type})"
                )

    if args.out_csv.strip():
        out_path = Path(args.out_csv.strip())
        write_out_csv(out_path, all_eval_rows)
        print(f"\n[INFO] wrote csv: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
