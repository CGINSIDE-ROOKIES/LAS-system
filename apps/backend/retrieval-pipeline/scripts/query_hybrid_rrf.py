#!/usr/bin/env python3
"""Qdrant(벡터) + OpenSearch(BM25) 하이브리드 검색 — RRF 방식으로 결과 융합.

사용 예시:
  uv run python scripts/query_hybrid_rrf.py --question "건설업 등록 기준은?" --top-k 5
  uv run python scripts/query_hybrid_rrf.py --question "연장근로는 최대 몇 시간까지?" --top-k 5
  uv run python scripts/query_hybrid_rrf.py --interactive --top-k 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

from retrieval_common import (
    DEFAULT_EMBEDDING_MODEL,
    RetrievalError,
    normalize_source_id,
    require_env_or_arg,
    search_bm25,
    search_qdrant,
)


# ── 문서 동일성 키 ────────────────────────────────────────────────────────────
def _rrf_key(row: dict[str, object]) -> str:
    """두 백엔드의 결과를 같은 문서인지 판별하기 위한 정규화 키를 반환한다.

    source_id가 있으면 정규화(suffix 제거)해서 키로 사용하고,
    없으면 텍스트 앞 800자의 SHA-1 해시를 fallback으로 사용한다.
    """
    sid = str(row.get("source_id", "") or "")
    key = normalize_source_id(sid) if sid else ""
    if key:
        return key
    text = str(row.get("text", "") or "")
    return f"text::{hashlib.sha1(text[:800].encode('utf-8')).hexdigest()}"


# ── 단일 백엔드 내 중복 제거 ──────────────────────────────────────────────────
def _dedup_backend_rows_for_rrf(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """단일 백엔드 결과에서 같은 문서가 여러 번 등장하면 가장 높은 순위(낮은 rank 숫자)만 남긴다.

    RRF 점수 계산 전에 각 백엔드 내부 중복을 제거해야 순위 왜곡을 방지할 수 있다.
    """
    best_by_key: dict[str, dict[str, object]] = {}  # 키 -> 대표 행
    best_rank_by_key: dict[str, int] = {}  # 키 -> 가장 좋은(낮은) rank

    for row in rows:
        rank = int(row.get("rank", 0) or 0)
        if rank <= 0:
            continue
        key = _rrf_key(row)
        prev_rank = best_rank_by_key.get(key)
        # 처음 등장이거나 현재 rank가 더 좋으면 갱신
        if prev_rank is None or rank < prev_rank:
            best_rank_by_key[key] = rank
            best_by_key[key] = row

    # rank 오름차순(=점수 내림차순)으로 정렬해서 반환
    return sorted(best_by_key.values(), key=lambda r: int(r.get("rank", 0) or 0))


# ── RRF 융합 ──────────────────────────────────────────────────────────────────
def fuse_rrf(
    qdrant_rows: list[dict[str, object]],
    os_rows: list[dict[str, object]],
    *,
    rrf_k: int,
    top_k: int,
) -> list[dict[str, object]]:
    """Qdrant + OpenSearch 결과를 RRF 방식으로 융합해 Top-K를 반환한다.

    RRF 점수 공식: score = Σ 1 / (k + rank_i)
      - k: 순위 편향 조절 상수 (보통 60). 클수록 하위 순위 문서도 점수를 받음.
      - rank_i: 각 백엔드에서의 순위 (1-based).
      - 두 백엔드에 모두 등장하면 점수가 합산되어 순위가 높아짐.

    동점(tie-break) 정렬 기준:
      1. rrf_score 내림차순
      2. 등장한 백엔드 수 내림차순 (두 백엔드에 모두 있으면 우선)
      3. 개별 백엔드 내 최고 rank 오름차순
      4. source_id 오름차순 (결정적 정렬 보장)

    Args:
        qdrant_rows: Qdrant 벡터 검색 결과.
        os_rows:     OpenSearch BM25 검색 결과.
        rrf_k:       RRF k 상수 (기본 60).
        top_k:       최종 반환할 결과 수.

    Returns:
        rank, score(=rrf_score), source_id 등이 포함된 결과 리스트.
    """
    # 문서 키 기준으로 두 백엔드 결과를 누적하는 딕셔너리
    merged: dict[str, dict[str, object]] = {}

    def add_rows(rows: list[dict[str, object]], backend: str) -> None:
        # 백엔드 결과를 merged에 RRF 점수로 누적
        deduped_rows = _dedup_backend_rows_for_rrf(rows)
        for row in deduped_rows:
            rank = int(row.get("rank", 0) or 0)
            if rank <= 0:
                continue

            sid = str(row.get("source_id", "") or "")
            key = _rrf_key(row)

            rrf_score = 1.0 / (rrf_k + rank)  # 이 백엔드에서의 RRF 기여 점수
            cur = merged.get(key)
            if cur is None:
                # 처음 등장: 새 항목 생성
                cur = {
                    "source_id": sid,
                    "doc_type": row.get("doc_type", ""),
                    "law_name": row.get("law_name", ""),
                    "text": row.get("text", ""),
                    "snippet": row.get("snippet", ""),
                    "rrf_score": 0.0,
                    "sources": [],  # 어느 백엔드에서 몇 위로 왔는지 기록
                }
                merged[key] = cur
            else:
                # 두 번째 백엔드에서 source_id가 보완될 수 있으면 업데이트
                if not str(cur.get("source_id", "") or "") and sid:
                    cur["source_id"] = sid

            # 기존 점수에 이번 백엔드 점수 누적
            cur["rrf_score"] = float(cur["rrf_score"]) + rrf_score

            # 출처 정보 추가 (디버깅 및 설명 목적)
            cast_sources = cur["sources"]
            if isinstance(cast_sources, list):
                cast_sources.append(
                    {"backend": backend, "rank": rank, "score": row.get("score")}
                )

    add_rows(qdrant_rows, "qdrant")
    add_rows(os_rows, "opensearch_bm25")

    def _tie_break_sort_key(row: dict[str, object]) -> tuple[float, int, int, str]:
        # 동점 시 정렬 기준 반환 (오름차순으로 정렬하므로 부호 반전에 주의)
        sources_obj = row.get("sources", [])
        source_count = 0
        best_rank = 10**9  # 초기값: 충분히 큰 수

        if isinstance(sources_obj, list):
            backends: set[str] = set()
            for s in sources_obj:
                if not isinstance(s, dict):
                    continue
                backend = str(s.get("backend", "") or "")
                if backend:
                    backends.add(backend)
                rank = int(s.get("rank", 0) or 0)
                if rank > 0:
                    best_rank = min(best_rank, rank)
            source_count = len(backends)

        if best_rank == 10**9:
            best_rank = 10**8  # sources가 비어있는 경우 안전값

        source_id = str(row.get("source_id", "") or "")
        return (
            -float(row["rrf_score"]),  # 1순위: 점수 내림차순
            -source_count,  # 2순위: 등장 백엔드 수 내림차순
            best_rank,  # 3순위: 최고 개별 rank 오름차순
            source_id,  # 4순위: source_id 오름차순 (결정적 정렬)
        )

    ranked = sorted(merged.values(), key=_tie_break_sort_key)

    # Top-k 추출 및 rank 부여
    out: list[dict[str, object]] = []
    for i, row in enumerate(ranked[: max(1, top_k)], start=1):
        out.append(
            {
                "rank": i,
                "score": round(float(row["rrf_score"]), 6),  # 수정: 소수점 6자리로 포맷
                "source_id": row.get("source_id", ""),
                "doc_type": row.get("doc_type", ""),
                "law_name": row.get("law_name", ""),
                "text": row.get("text", ""),
                "snippet": row.get("snippet", ""),
                "sources": row.get("sources", []),
            }
        )
    return out


# ── LLM 컨텍스트 빌딩 ────────────────────────────────────────────────────────
def _clean_content(text: str) -> str:
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
    for idx, ctx in enumerate(contexts, start=1):
        lines.append(
            f"{idx}. source_id={ctx.get('source_id', '')} law_name={ctx.get('law_name', '')} doc_type={ctx.get('doc_type', '')}"
        )
        lines.append(str(ctx.get("content", "")))
        lines.append("")
    return "\n".join(lines).strip()


# ── 결과 출력 ────────────────────────────────────────────────────────────────
def print_results(question: str, rows: list[dict[str, object]]) -> None:
    # merge 결과를 콘솔에 출력, sources 정보로 어디서 왔는지도 표시
    print(f"\n[Q] {question}")
    if not rows:
        print("[INFO] 검색 결과 없음")
        return

    for row in rows:
        print(f"\n#{row['rank']} score={row['score']:.6f}")
        sid = str(row.get("source_id", "") or "")
        if sid:
            print(f"source_id: {sid}")
        doc_type = str(row.get("doc_type", "") or "")
        law_name = str(row.get("law_name", "") or "")
        if doc_type or law_name:
            print(f"meta: doc_type={doc_type} law_name={law_name}")

        # 어느 백엔드에서 몇 위로 왔는지 출력 (디버깅에 유용)
        sources = row.get("sources", [])
        if isinstance(sources, list) and sources:
            src_strs = [
                f"{s.get('backend','?')}@{s.get('rank','?')}"
                for s in sources
                if isinstance(s, dict)
            ]
            print(f"sources: {', '.join(src_strs)}")

        snippet = str(row.get("snippet", "") or "")
        if snippet:
            print(f"text: {snippet}")


# ── 단일 질문 실행 ────────────────────────────────────────────────────────────
def run_single_query(args: argparse.Namespace, question: str) -> int:
    # Qdrant 연결 정보
    qdrant_url = require_env_or_arg(
        args.qdrant_url, "QDRANT_URL", "http://localhost:6333"
    )
    qdrant_collection = require_env_or_arg(args.qdrant_collection, "QDRANT_COLLECTION")
    qdrant_api_key = (
        args.qdrant_api_key or os.getenv("QDRANT_API_KEY", "").strip() or None
    )

    # OpenSearch 연결 정보
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

    # 각 백엔드에서 가져올 후보 수 결정
    # top_k보다 candidate_k가 작으면 top_k를 사용 (RRF 융합 품질 보장)
    candidate_k = max(args.top_k, args.candidate_k)

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

    # 3. RRF merge
    fused_raw = fuse_rrf(qdrant_rows, os_rows, rrf_k=args.rrf_k, top_k=args.top_k)

    # 4. (선택) 규범형 질의 시 law 문서 점수 가산 후 재정렬
    fused = _apply_law_boost(
        fused_raw,
        question=question,
        enabled=args.auto_law_boost,
        law_boost_score=args.law_boost_score,
    )[: max(1, args.top_k)]

    # 5. LLM 컨텍스트 빌드 (--llm-context-* 플래그 사용 시)
    llm_rows, law_context_added = _select_llm_rows(
        fused,
        top_k=args.top_k,
        min_law_contexts=args.min_law_contexts,
    )
    contexts = _build_llm_context_rows(
        llm_rows,
        max_content_chars=args.max_content_chars,
        max_total_chars=args.max_total_chars,
    )

    if args.llm_context_json:
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
        print(_build_llm_context_text(question, contexts, law_context_added))
        return 0

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
        return 0

    print_results(question, fused)
    return 0


# ── CLI 인자 정의 ─────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="사용자 질문 → Hybrid RRF Top-K 검색")

    # 질문 입력
    p.add_argument("--question", default="", help="질문 텍스트 (단일 실행)")
    p.add_argument("--interactive", action="store_true", help="대화형 모드")

    # 검색 파라미터
    p.add_argument("--top-k", type=int, default=5, help="최종 반환 결과 수")
    p.add_argument(
        "--candidate-k", type=int, default=30, help="백엔드별 후보 수 (RRF 전 단계)"
    )
    p.add_argument(
        "--rrf-k", type=int, default=60, help="RRF k 상수 (클수록 하위 순위 영향 증가)"
    )
    p.add_argument("--timeout", type=int, default=120, help="요청 타임아웃 (초)")

    # Qdrant 연결
    p.add_argument(
        "--qdrant-url", default="", help="기본: QDRANT_URL 또는 http://localhost:6333"
    )
    p.add_argument(
        "--qdrant-collection", default="", help="기본: QDRANT_COLLECTION 환경변수"
    )
    p.add_argument("--qdrant-api-key", default="", help="기본: QDRANT_API_KEY 환경변수")

    # OpenSearch 연결
    p.add_argument(
        "--opensearch-url",
        default="",
        help="기본: OPENSEARCH_URL 또는 http://localhost:9200",
    )
    p.add_argument(
        "--opensearch-index", default="", help="기본: OPENSEARCH_INDEX 환경변수"
    )
    p.add_argument(
        "--opensearch-api-key", default="", help="기본: OPENSEARCH_API_KEY 환경변수"
    )
    p.add_argument(
        "--opensearch-username", default="", help="기본: OPENSEARCH_USERNAME 환경변수"
    )
    p.add_argument(
        "--opensearch-password", default="", help="기본: OPENSEARCH_PASSWORD 환경변수"
    )

    # 공통 옵션
    p.add_argument(
        "--embedding-model", default="", help=f"기본: {DEFAULT_EMBEDDING_MODEL}"
    )
    p.add_argument(
        "--doc-type", action="append", default=[], help="doc_type 필터 (복수 가능)"
    )
    p.add_argument(
        "--law-name", action="append", default=[], help="law_name 필터 (복수 가능)"
    )
    p.add_argument("--json", action="store_true", help="결과를 JSON 형태로 출력")
    p.add_argument(
        "--llm-context-json",
        action="store_true",
        help="RRF 결과를 LLM 입력용 JSON 컨텍스트 배열로 출력",
    )
    p.add_argument(
        "--llm-context-text",
        action="store_true",
        help="RRF 결과를 LLM 프롬프트용 텍스트로 출력",
    )
    p.add_argument("--max-content-chars", type=int, default=1200, help="컨텍스트 문서당 최대 글자 수")
    p.add_argument("--max-total-chars", type=int, default=6000, help="컨텍스트 전체 최대 글자 수")
    p.add_argument(
        "--min-law-contexts",
        type=int,
        default=1,
        help="LLM 컨텍스트에 포함할 최소 law 문서 수 (기본: 1)",
    )
    p.add_argument(
        "--auto-law-boost",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="기준/요건/의무형 질의에서 law 문서 점수 자동 가산 (기본: on)",
    )
    p.add_argument(
        "--law-boost-score",
        type=float,
        default=0.003,
        help="auto-law-boost 적용 시 law 문서 점수 가산치",
    )

    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.interactive:
        print("Hybrid RRF 검색 대화형 모드  |  종료: :q / quit / exit")
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
            try:
                run_single_query(args, q)
            except RetrievalError as e:
                print(f"[ERROR] {e}")

    if not args.question.strip():
        raise SystemExit(
            "오류: --question 또는 --interactive 중 하나는 지정해야 합니다."
        )

    return run_single_query(args, args.question.strip())


if __name__ == "__main__":
    sys.exit(main())
