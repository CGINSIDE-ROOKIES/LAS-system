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
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def qdrant_numeric_id(source_id: str) -> int:
    import hashlib

    digest = hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)


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

    model = SentenceTransformer(model_name)
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist() if hasattr(vec, "tolist") else list(vec)


def build_filter(
    doc_types: list[str] | None, law_names: list[str] | None
) -> dict[str, Any] | None:
    must: list[dict[str, Any]] = []
    if doc_types:
        must.append(
            {
                "key": "doc_type",
                "match": {"any": doc_types},
            }
        )
    if law_names:
        must.append(
            {
                "key": "law_name",
                "match": {"any": law_names},
            }
        )

    if not must:
        return None
    return {"must": must}


def _dedup_by_source_id(rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """source_id 기준 중복 제거 후 top_k 반환 (score 내림차순 유지)."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        sid = (row.get("payload") or {}).get("source_id", "")
        key = sid if sid else f"__id_{row.get('id')}"
        if key not in seen:
            seen.add(key)
            deduped.append(row)
        if len(deduped) >= top_k:
            break
    return deduped


def qdrant_search(
    *,
    qdrant_url: str,
    collection: str,
    api_key: str | None,
    vector: list[float],
    top_k: int,
    timeout: int,
    query_source_id: str | None,
    doc_types: list[str] | None,
    law_names: list[str] | None,
) -> list[dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    must_not: list[dict[str, Any]] = []
    if query_source_id:
        must_not.append({"has_id": [qdrant_numeric_id(query_source_id)]})

    # 중복 제거 후 top_k를 맞추기 위해 여유분(x2) 요청
    fetch_limit = max(1, top_k * 2)

    payload: dict[str, Any] = {
        "vector": vector,
        "limit": fetch_limit,
        "with_payload": True,
        "with_vector": False,
    }

    filt = build_filter(doc_types, law_names)
    if filt or must_not:
        filter_obj = filt or {}
        if must_not:
            filter_obj["must_not"] = must_not
        payload["filter"] = filter_obj

    url = f"{qdrant_url.rstrip('/')}/collections/{urllib.parse.quote(collection)}/points/search"
    res = http_json("POST", url, payload, headers, timeout)
    result = res.get("result", [])
    rows = result if isinstance(result, list) else []
    return _dedup_by_source_id(rows, top_k)


def normalize_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        payload = row.get("payload") or {}
        text = str(payload.get("text", "") or "")
        normalized.append(
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
    qdrant_url = require_env_or_arg(
        args.qdrant_url, "QDRANT_URL", "http://localhost:6333"
    )
    collection = require_env_or_arg(args.collection, "QDRANT_COLLECTION")
    model_name = require_env_or_arg(
        args.embedding_model, "EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
    )
    api_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY", "").strip() or None

    vector = embed_query(question, model_name)
    rows = qdrant_search(
        qdrant_url=qdrant_url,
        collection=collection,
        api_key=api_key,
        vector=vector,
        top_k=args.top_k,
        timeout=args.timeout,
        query_source_id=None,
        doc_types=args.doc_type or None,
        law_names=args.law_name or None,
    )
    normalized = normalize_results(rows)

    if args.json:
        print(
            json.dumps(
                {
                    "backend": "qdrant",
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
