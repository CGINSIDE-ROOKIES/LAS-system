#!/usr/bin/env python3
"""Qdrant 벡터 DB 밀집(dense) 검색 스크립트

사용 예시 :
1) 단일 질문
   uv run python cli/query_qdrant_topk.py --question "건설업 등록 기준은?" --top-k 5
   uv run python cli/query_qdrant_topk.py --question "연장근로 최대 시간은 몇 시간인가요?" --top-k 5

2) 대화형 모드
   uv run python cli/query_qdrant_topk.py --interactive
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from retrieval_common import (
    DEFAULT_EMBEDDING_MODEL,
    RetrievalError,
    require_env_or_arg,
    search_qdrant,
)


#  ── 결과 출력 ────────────────────────────────────────────────────────────────


def print_results(question: str, rows: list[dict[str, object]]) -> None:
    print(f"\n[Q] {question}")
    if not rows:
        print("[INFO] 검색 결과 없음")
        return

    for row in rows:
        print(f"\n#{row['rank']} score={row['score']}")  # 수정: 소수점 4자리로 포맷
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


#  ── 법령 부스팅 로직 ─────────────────────────────────────────────────────────
# 규범적 질의 여부를 판단하는 키워드 목록
# 실험을 통해 키워드·가산치를 지속적으로 튜닝해야 함
_NORMATIVE_KEYWORDS = (
    "기준",
    "요건",
    "의무",
    "절차",
    "서면",
    "신청",
    "작성",
    "반드시",
    "해야",
    "가능",
    "조건",
)


def _is_normative_query(question: str) -> bool:
    """질문이 법령/규정 관련 규범적 질의인지 키워드 기반으로 판단한다."""
    q = question.strip()
    return any(k in q for k in _NORMATIVE_KEYWORDS)


def _apply_law_boost(
    rows: list[dict[str, object]],
    *,
    question: str,
    enabled: bool,
    law_boost_score: float,
) -> list[dict[str, object]]:
    """규범적 질의일 경우 doc_type='law' 문서의 점수를 가산해 재정렬한다.

    Args:
        rows: 원본 검색 결과 리스트.
        question: 사용자 질문 (규범적 질의 여부 판단에 사용).
        enabled: 부스팅 활성화 여부 (--auto-law-boost 옵션).
        law_boost_score: law 문서에 더할 점수 가산치.

    Returns:
        점수 재계산 및 재정렬된 결과 리스트.
    """
    # 비활성화되었거나 결과가 없거나 규범적 질의가 아니면 원본 그대로 반환
    if not enabled or not rows or not _is_normative_query(question):
        return rows

    boosted: list[dict[str, object]] = []
    for row in rows:
        score = float(row.get("score", 0.0) or 0.0)

        # law 문서에만 가산점 부여
        if str(row.get("doc_type", "") or "") == "law":
            score += law_boost_score

        cloned = dict(row)  # 원본 딕셔너리를 변경하지 않기 위해 복사
        cloned["score"] = score
        boosted.append(cloned)

    # 점수 내림차순 → 동점 시 source_id 오름차순으로 정렬
    boosted.sort(
        key=lambda r: (
            -float(r.get("score", 0.0) or 0.0),
            str(r.get("source_id", "") or ""),
        )
    )

    # rank 재부여
    for i, row in enumerate(boosted, start=1):
        row["rank"] = i

    return boosted


# ── 단일 질문 실행 ────────────────────────────────────────────────────────────
def run_single_query(args: argparse.Namespace, question: str) -> int:
    # 환경변수 또는 CLI 인자에서 연결 정보를 가져옴
    qdrant_url = require_env_or_arg(
        args.qdrant_url, "QDRANT_URL", "http://localhost:6333"
    )
    collection = require_env_or_arg(args.collection, "QDRANT_COLLECTION")
    model_name = require_env_or_arg(
        args.embedding_model, "EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
    )
    api_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY", "").strip() or None

    # Qdrant에서 유사 벡터 Top-K 검색
    rows = search_qdrant(
        question,
        args.top_k,
        qdrant_url=qdrant_url,
        collection=collection,
        timeout=args.timeout,
        embedding_model=model_name,
        api_key=api_key,
        doc_types=args.doc_type or None,  # 빈 리스트는 None으로 변환 (필터 미적용)
        law_names=args.law_name or None,
        dedup=True,  # 중복 문서 제거
        fetch_multiplier=2,  # dedup 여유분 확보를 위해 top_k * 2 만큼 먼저 가져옴
    )

    # 규범적 질의라면 law 문서 점수 가산 후 재정렬
    rows = _apply_law_boost(
        rows,
        question=question,
        enabled=args.auto_law_boost,
        law_boost_score=args.law_boost_score,
    )

    if args.json:
        # 구조화된 JSON 출력 (파이프라인 연계 등에 활용)
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


# ── CLI 인자 정의 ─────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    """CLI 인자를 파싱하여 반환한다."""
    p = argparse.ArgumentParser(description="사용자 질문 → Qdrant Top-K 검색")

    # 질문 입력 방식
    p.add_argument("--question", default="", help="질문 텍스트 (단일 실행)")
    p.add_argument("--interactive", action="store_true", help="대화형 모드")

    # 검색 파라미터
    p.add_argument("--top-k", type=int, default=5, help="반환할 최대 결과 수")
    p.add_argument("--timeout", type=int, default=120, help="Qdrant 요청 타임아웃 (초)")

    # 연결 정보 (환경변수로도 대체 가능)
    p.add_argument(
        "--qdrant-url", default="", help="기본: QDRANT_URL 또는 http://localhost:6333"
    )
    p.add_argument("--collection", default="", help="기본: QDRANT_COLLECTION 환경변수")
    p.add_argument("--qdrant-api-key", default="", help="기본: QDRANT_API_KEY 환경변수")
    p.add_argument(
        "--embedding-model", default="", help=f"기본: {DEFAULT_EMBEDDING_MODEL}"
    )

    # 필터링 (복수 지정 가능: --doc-type law --doc-type faq)
    p.add_argument(
        "--doc-type", action="append", default=[], help="payload.doc_type 필터"
    )
    p.add_argument(
        "--law-name", action="append", default=[], help="payload.law_name 필터"
    )

    # 법령 부스팅 설정
    p.add_argument(
        "--auto-law-boost",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="기준/요건/의무형 질의에서 law 문서 점수 자동 가산 (기본: on, 끄려면 --no-auto-law-boost)",
    )
    p.add_argument(
        "--law-boost-score",
        type=float,
        default=0.003,
        help="auto-law-boost 적용 시 law 문서 점수 가산치 (기본: 0.003)",
    )

    # 출력 형식
    p.add_argument("--json", action="store_true", help="결과를 JSON 형태로 출력")

    return p.parse_args()


# ── 진입점 ────────────────────────────────────────────────────────────────────
def main() -> int:
    args = parse_args()

    if args.interactive:
        # 대화형 모드: 질문을 반복 입력받아 검색
        print("Qdrant 검색 대화형 모드  |  종료: :q / quit / exit")
        while True:
            try:
                q = input("\n질문> ").strip()
            except (EOFError, KeyboardInterrupt):
                # Ctrl+D / Ctrl+C 로 정상 종료
                print()
                return 0
            if not q:
                continue
            if q in {":q", "quit", "exit"}:
                return 0
            try:
                run_single_query(args, q)
            except RetrievalError as e:
                # 대화형 모드에서는 오류를 출력하고 다음 질문으로 계속 진행
                print(f"[ERROR] {e}")

    # 단일 실행 모드: --question 필수
    if not args.question.strip():
        raise SystemExit(
            "오류: --question 또는 --interactive 중 하나는 지정해야 합니다."
        )

    try:
        return run_single_query(args, args.question.strip())
    except RetrievalError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    sys.exit(main())
