#!/usr/bin/env python3
"""한 질의에 대해 Qdrant(벡터) / BM25(키워드) / Hybrid RRF 결과를 한번에 보는 통합 실행 엔트리포인트.

사용 예시:
  uv run python scripts/query_all_retrieval.py --question "연장근로 최대 시간은?" --top-k 5
  uv run python scripts/query_all_retrieval.py --interactive --top-k 5
  uv run python scripts/query_all_retrieval.py --question "..." --llm-context-json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from query_hybrid_rrf import fuse_rrf
from retrieval_common import (
    DEFAULT_EMBEDDING_MODEL,
    RetrievalError,
    require_env_or_arg,
    search_bm25,
    search_qdrant,
)


# ── 개별 백엔드 결과 출력 ─────────────────────────────────────────────────────
def _print_backend_results(title: str, rows: list[dict[str, object]]) -> None:
    """단일 백엔드(Qdrant / BM25 / RRF)의 검색 결과를 섹션 제목과 함께 출력한다."""
    print(f"\n[{title}]")
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
        # RRF 결과에는 sources(출처 백엔드 정보)가 포함됨
        sources = row.get("sources", [])
        if isinstance(sources, list) and sources:
            src_strs = [
                f"{s.get('backend', '?')}@{s.get('rank', '?')}"
                for s in sources
                if isinstance(s, dict)
            ]
            print(f"sources: {', '.join(src_strs)}")
        if snippet:
            print(f"text: {snippet}")


# ── LLM 컨텍스트 빌딩 ────────────────────────────────────────────────────────
def _clean_content(text: str) -> str:
    """연속 공백·개행을 단일 공백으로 정규화한다."""
    return re.sub(r"\s+", " ", text).strip()


def _is_normative_query(question: str) -> bool:
    """기준·요건·의무 등 규범형 질의인지 판별한다."""
    keywords = ("기준", "요건", "의무", "절차", "서면", "신청", "작성", "반드시", "해야", "가능", "조건")
    return any(k in question.strip() for k in keywords)


def _apply_law_boost(
    rows: list[dict[str, object]],
    *,
    question: str,
    enabled: bool,
    law_boost_score: float,
) -> list[dict[str, object]]:
    """규범형 질의일 때 law 문서 score에 가산점을 부여하고 재정렬한다."""
    if not enabled or not rows or not _is_normative_query(question):
        return rows

    boosted: list[dict[str, object]] = []
    for row in rows:
        score = float(row.get("score", 0.0) or 0.0)
        if str(row.get("doc_type", "") or "") == "law":
            score += law_boost_score
        cloned = dict(row)
        cloned["score"] = score
        boosted.append(cloned)

    boosted.sort(
        key=lambda r: (
            -float(r.get("score", 0.0) or 0.0),
            str(r.get("source_id", "") or ""),
        )
    )
    for i, row in enumerate(boosted, start=1):
        row["rank"] = i
    return boosted


def _select_llm_rows(
    rows: list[dict[str, object]],
    *,
    top_k: int,
    min_law_contexts: int,
) -> tuple[list[dict[str, object]], bool]:
    """LLM에 넘길 행을 선택하고, 최소 law 문서 수 충족 여부를 함께 반환한다."""
    selected = list(rows[: max(1, top_k)])
    if min_law_contexts <= 0:
        return selected, True
    law_count = sum(1 for r in selected if str(r.get("doc_type", "") or "") == "law")
    return selected, law_count >= min_law_contexts


def _build_llm_context_rows(
    rows: list[dict[str, object]],
    *,
    max_content_chars: int,
    max_total_chars: int,
) -> list[dict[str, object]]:
    """LLM 입력용 컨텍스트 배열을 빌드한다. 글자 수 제한을 적용한다."""
    out: list[dict[str, object]] = []
    total = 0
    for row in rows:
        text = str(row.get("text", "") or "")
        snippet = str(row.get("snippet", "") or "")
        content = _clean_content(text or snippet)
        if not content:
            continue
        if max_content_chars > 0:
            content = content[:max_content_chars]
        if max_total_chars > 0 and total + len(content) > max_total_chars:
            remain = max_total_chars - total
            if remain <= 0:
                break
            content = content[:remain]
        out.append(
            {
                "source_id": str(row.get("source_id", "") or ""),
                "law_name": str(row.get("law_name", "") or ""),
                "doc_type": str(row.get("doc_type", "") or ""),
                "score": row.get("score"),
                "content": content,
            }
        )
        total += len(content)
    return out


def _build_llm_context_text(
    question: str,
    contexts: list[dict[str, object]],
    law_context_added: bool,
) -> str:
    """LLM 프롬프트에 바로 삽입할 수 있는 텍스트 형식으로 컨텍스트를 포맷한다."""
    lines: list[str] = [f"[질문]\n{question}", "", "[컨텍스트]"]
    if not law_context_added:
        lines.append("[주의] 이번 결과에는 요청한 수의 law 문서가 없어 law 컨텍스트를 추가하지 않았습니다.")
        lines.append("")
    if not contexts:
        lines.append("(없음)")
        return "\n".join(lines)
    for i, ctx in enumerate(contexts, start=1):
        lines.append(
            f"{i}. source_id={ctx.get('source_id', '')} law_name={ctx.get('law_name', '')} doc_type={ctx.get('doc_type', '')}"
        )
        lines.append(str(ctx.get("content", "")))
        lines.append("")
    return "\n".join(lines).strip()


# ── 단일 질문 실행 ────────────────────────────────────────────────────────────
def run_single_query(args: argparse.Namespace, question: str) -> int:
    # ── 연결 정보 로드 ──────────────────────────────────────────────────────────
    qdrant_url = require_env_or_arg(args.qdrant_url, "QDRANT_URL", "http://localhost:6333")
    qdrant_collection = require_env_or_arg(args.qdrant_collection, "QDRANT_COLLECTION")
    qdrant_api_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY", "").strip() or None

    opensearch_url = require_env_or_arg(args.opensearch_url, "OPENSEARCH_URL", "http://localhost:9200")
    opensearch_index = require_env_or_arg(args.opensearch_index, "OPENSEARCH_INDEX")
    os_api_key = args.opensearch_api_key or os.getenv("OPENSEARCH_API_KEY", "").strip() or None
    os_user = args.opensearch_username or os.getenv("OPENSEARCH_USERNAME", "").strip() or None
    os_pass = args.opensearch_password or os.getenv("OPENSEARCH_PASSWORD", "").strip() or None

    model_name = require_env_or_arg(args.embedding_model, "EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)

    # top_k보다 candidate_k가 작으면 top_k를 사용 (RRF 융합 품질 보장)
    candidate_k = max(args.top_k, args.candidate_k)

    try:
        # 1. Qdrant 벡터 검색
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
        # 2. OpenSearch BM25 키워드 검색
        bm25_rows = search_bm25(
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
    except RetrievalError as e:
        raise SystemExit(f"[ERROR] 검색 실패: {e}") from e

    # 3. RRF 융합
    rrf_rows = fuse_rrf(qdrant_rows, bm25_rows, rrf_k=args.rrf_k, top_k=args.top_k)

    # 4. (선택) 규범형 질의 시 law 문서 점수 가산 후 재정렬
    rrf_rows = _apply_law_boost(
        rrf_rows,
        question=question,
        enabled=args.auto_law_boost,
        law_boost_score=args.law_boost_score,
    )[: max(1, args.top_k)]

    # 각 백엔드 Top-k 슬라이싱 (출력·JSON용)
    qdrant_top = qdrant_rows[: max(1, args.top_k)]
    bm25_top = bm25_rows[: max(1, args.top_k)]

    # 5. LLM 컨텍스트 빌드
    llm_rows, law_context_added = _select_llm_rows(
        rrf_rows, top_k=args.top_k, min_law_contexts=args.min_law_contexts
    )
    contexts = _build_llm_context_rows(
        llm_rows,
        max_content_chars=args.max_content_chars,
        max_total_chars=args.max_total_chars,
    )

    # ── 출력 모드 분기 ──────────────────────────────────────────────────────────
    if args.llm_context_json:
        # LLM에 넘기기 위한 JSON 컨텍스트만 출력
        print(
            json.dumps(
                {
                    "question": question,
                    "top_k": args.top_k,
                    "min_law_contexts": args.min_law_contexts,
                    "law_context_added": law_context_added,
                    "contexts": contexts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.llm_context_text:
        # LLM 프롬프트에 바로 붙여넣을 수 있는 텍스트 출력
        print(_build_llm_context_text(question, contexts, law_context_added))
        return 0

    if args.json:
        # 세 백엔드 결과를 모두 JSON으로 출력
        print(
            json.dumps(
                {
                    "question": question,
                    "top_k": args.top_k,
                    "candidate_k": candidate_k,
                    "rrf_k": args.rrf_k,
                    "results": {
                        "qdrant": qdrant_top,
                        "opensearch_bm25": bm25_top,
                        "hybrid_rrf": rrf_rows,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    # 기본: Qdrant / BM25 / RRF 결과를 순서대로 사람이 읽을 수 있는 형태로 출력
    print(f"\n[Q] {question}")
    _print_backend_results("QDRANT", qdrant_top)
    _print_backend_results("BM25", bm25_top)
    _print_backend_results("RRF", rrf_rows)
    return 0


# ── CLI 인자 정의 ─────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Qdrant / BM25 / Hybrid RRF 통합 검색")

    # 질문 입력
    p.add_argument("--question", default="", help="질문 텍스트 (단일 실행)")
    p.add_argument("--interactive", action="store_true", help="대화형 모드")

    # 검색 파라미터
    p.add_argument("--top-k", type=int, default=5, help="최종 출력 개수")
    p.add_argument("--candidate-k", type=int, default=30, help="백엔드별 후보 수 (RRF 전 단계)")
    p.add_argument("--rrf-k", type=int, default=60, help="RRF k 상수 (클수록 하위 순위 영향 증가)")
    p.add_argument("--timeout", type=int, default=120, help="요청 타임아웃 (초)")

    # Qdrant 연결
    p.add_argument("--qdrant-url", default="", help="기본: QDRANT_URL 또는 http://localhost:6333")
    p.add_argument("--qdrant-collection", default="", help="기본: QDRANT_COLLECTION 환경변수")
    p.add_argument("--qdrant-api-key", default="", help="기본: QDRANT_API_KEY 환경변수")

    # OpenSearch 연결
    p.add_argument("--opensearch-url", default="", help="기본: OPENSEARCH_URL 또는 http://localhost:9200")
    p.add_argument("--opensearch-index", default="", help="기본: OPENSEARCH_INDEX 환경변수")
    p.add_argument("--opensearch-api-key", default="", help="기본: OPENSEARCH_API_KEY 환경변수")
    p.add_argument("--opensearch-username", default="", help="기본: OPENSEARCH_USERNAME 환경변수")
    p.add_argument("--opensearch-password", default="", help="기본: OPENSEARCH_PASSWORD 환경변수")

    # 공통 옵션
    p.add_argument("--embedding-model", default="", help=f"기본: {DEFAULT_EMBEDDING_MODEL}")
    p.add_argument("--doc-type", action="append", default=[], help="doc_type 필터 (복수 가능)")
    p.add_argument("--law-name", action="append", default=[], help="law_name 필터 (복수 가능)")
    p.add_argument("--json", action="store_true", help="세 백엔드 결과를 JSON으로 출력")

    # LLM 컨텍스트 출력 옵션
    p.add_argument("--llm-context-json", action="store_true", help="RRF 결과를 LLM 입력용 JSON 컨텍스트로 출력")
    p.add_argument("--llm-context-text", action="store_true", help="RRF 결과를 LLM 프롬프트용 텍스트로 출력")
    p.add_argument("--max-content-chars", type=int, default=1200, help="컨텍스트 문서당 최대 글자 수")
    p.add_argument("--max-total-chars", type=int, default=6000, help="컨텍스트 전체 최대 글자 수")
    p.add_argument("--min-law-contexts", type=int, default=1, help="LLM 컨텍스트에 포함할 최소 law 문서 수")

    # Law boost 옵션
    p.add_argument(
        "--auto-law-boost",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="기준/요건/의무형 질의에서 law 문서 점수 자동 가산 (기본: on)",
    )
    p.add_argument("--law-boost-score", type=float, default=0.003, help="auto-law-boost 적용 시 law 문서 점수 가산치")

    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.interactive:
        print("통합 검색 대화형 모드  |  종료: :q / quit / exit")
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
