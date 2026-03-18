#!/usr/bin/env python3
"""Retrieval + Generator 통합 실행 스크립트.

실행 예시:
  uv run python cli/generate_answer.py --question "연장근로 최대 시간은?"

스트리밍(NDJSON):
  uv run python cli/generate_answer.py --question "연장근로 최대 시간은?" --stream

텍스트 스트리밍 확인:
  uv run python cli/generate_answer.py --question "연장근로 최대 시간은?" --stream --text

길이 제한 + temperature 설정:
  uv run python cli/generate_answer.py --question "연장근로 최대 시간은?" --top-k 2 --max-content-chars 400 --max-total-chars 900 --llm-max-input-chars 1200 --llm-max-tokens 200 --llm-temperature 0.1
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

# 실행 위치와 관계없이 로컬 cli 모듈 import 가능하도록 경로 고정
CLI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from generator import (
    DEFAULT_CHAT_COMPLETIONS_URL,
    DEFAULT_MODEL,
    generate_answer,
    stream_answer,
)
from query_all_retrieval import (
    _apply_law_boost,
    _build_llm_context_rows,
    _build_llm_context_text,
)
from query_hybrid_rrf import fuse_rrf
from retrieval_common import (
    DEFAULT_EMBEDDING_MODEL,
    RetrievalError,
    require_env_or_arg,
    search_bm25,
    search_qdrant,
)

DEFAULT_ANSWER_BASELINE_PROMPT = (
    "당신은 법률 Q&A 보조 시스템입니다.\n"
    "반드시 제공된 컨텍스트 안의 정보만 근거로 답변하세요.\n"
    "컨텍스트에 없는 사실은 추측하거나 단정하지 마세요.\n"
    "근거가 부족하면 반드시 '근거 부족'이라고 명시하세요.\n"
    "상충되는 근거가 있으면 상충 사실을 먼저 밝히세요.\n\n"
    "다음 형식을 반드시 지켜 답변하세요:\n"
    "요약 답변: <1~3문장>\n"
    "근거:\n"
    "- <핵심 근거 1> (law_name=<...>, doc_type=<...>, source_id=<...>)\n"
    "- <핵심 근거 2> (law_name=<...>, doc_type=<...>, source_id=<...>)\n"
    "근거 부족/한계: <없음 또는 부족 사유 1문장>"
)


def _is_law_row(row: dict[str, object]) -> bool:
    return str(row.get("doc_type", "") or "") == "law"


def _rank_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    ranked = sorted(
        (dict(r) for r in rows),
        key=lambda r: (
            -float(r.get("score", 0.0) or 0.0),
            str(r.get("source_id", "") or ""),
        ),
    )
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i
    return ranked


def _select_rows_with_law_policy(
    *,
    rows: list[dict[str, object]],
    top_k: int,
    min_law_contexts: int,
    enforce_min_law_contexts: bool,
) -> tuple[list[dict[str, object]], str, bool]:
    selected = list(rows[: max(1, top_k)])
    if min_law_contexts <= 0:
        return _rank_rows(selected), "ok", True

    law_count = sum(1 for r in selected if _is_law_row(r))
    if law_count >= min_law_contexts:
        return _rank_rows(selected), "ok", True

    if not enforce_min_law_contexts:
        return _rank_rows(selected), "missing", False

    selected_ids = {str(r.get("source_id", "") or "") for r in selected}
    extra_law_pool: list[dict[str, object]] = []
    for row in rows[max(1, top_k) :]:
        if not _is_law_row(row):
            continue
        source_id = str(row.get("source_id", "") or "")
        if source_id and source_id in selected_ids:
            continue
        extra_law_pool.append(dict(row))

    needed = max(0, min_law_contexts - law_count)
    replacements = min(needed, len(extra_law_pool))
    if replacements <= 0:
        return _rank_rows(selected), "missing", False

    non_law_indexes = [i for i, r in enumerate(selected) if not _is_law_row(r)]
    if not non_law_indexes:
        return _rank_rows(selected), "missing", False

    replace_slots = list(reversed(non_law_indexes))[:replacements]
    for slot, law_row in zip(replace_slots, extra_law_pool[:replacements]):
        selected[slot] = law_row

    selected_ranked = _rank_rows(selected)
    final_law_count = sum(1 for r in selected_ranked if _is_law_row(r))
    if final_law_count >= min_law_contexts:
        return selected_ranked, "supplemented", True
    return selected_ranked, "missing", False


def _build_frontend_payload(
    *,
    question: str,
    answer: str,
    retrieved_docs: list[dict[str, object]],
    snippet_max_chars: int,
    include_question: bool,
    law_context_status: str,
    law_context_added: bool,
) -> dict[str, object]:
    def _clip(text: str, limit: int) -> str:
        if limit <= 0:
            return text
        return text[:limit]

    seen: set[str] = set()
    sources: list[dict[str, object]] = []
    for row in retrieved_docs:
        source_id = str(row.get("source_id", "") or "")
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        sources.append(
            {
                "source_id": source_id,
                "rank": row.get("rank"),
                "doc_type": str(row.get("doc_type", "") or ""),
                "law_name": str(row.get("law_name", "") or ""),
                "score": row.get("score"),
            }
        )

    docs_out: list[dict[str, object]] = []
    for row in retrieved_docs:
        docs_out.append(
            {
                "rank": row.get("rank"),
                "source_id": str(row.get("source_id", "") or ""),
                "doc_type": str(row.get("doc_type", "") or ""),
                "law_name": str(row.get("law_name", "") or ""),
                "score": row.get("score"),
                "snippet": _clip(str(row.get("snippet", "") or ""), snippet_max_chars),
            }
        )

    payload: dict[str, object] = {
        "answer": answer,
        "sources": sources,
        "retrieved_docs": docs_out,
        "law_context_status": law_context_status,
        "law_context_added": law_context_added,
    }
    if include_question:
        payload["question"] = question
    return payload


def _build_user_prompt_with_limit(
    *,
    retrieved_context_text: str,
    question: str,
    max_input_chars: int,
    law_context_status: str,
) -> str:
    """system_prompt를 제외한 user 메시지 본문(컨텍스트 + 질문)을 조립한다."""
    status_line = ""
    if law_context_status == "missing":
        status_line = (
            "중요: 현재 검색 결과에서 법령(law) 근거가 충분하지 않습니다.\n"
            "확정적 결론 대신 근거 부족을 명시하고, 확인 가능한 범위만 답변하세요.\n\n"
        )
    elif law_context_status == "supplemented":
        status_line = "참고: 법령(law) 문서를 보강한 컨텍스트로 답변합니다.\n\n"

    prefix = (
        f"{status_line}"
        "아래 검색 컨텍스트를 근거로만 답변하세요.\n"
        "근거가 부족하면 부족하다고 명시하세요.\n\n"
    )
    suffix = f"\n\n[최종 질문]\n{question}"

    if max_input_chars <= 0:
        return f"{prefix}{retrieved_context_text}{suffix}"

    keep = max_input_chars - len(prefix) - len(suffix)
    if keep <= 0:
        return f"[최종 질문]\n{question}"

    context = retrieved_context_text
    if len(context) > keep:
        context = context[:keep]
    return f"{prefix}{context}{suffix}"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Retrieval + Generator 통합 실행기")
    p.add_argument("--question", default="", help="질문 텍스트")
    p.add_argument("--interactive", action="store_true", help="대화형 질의 모드")
    p.add_argument("--top-k", type=int, default=5, help="최종 컨텍스트 문서 수")
    p.add_argument("--candidate-k", type=int, default=30, help="백엔드별 후보 수")
    p.add_argument("--rrf-k", type=int, default=60, help="RRF k 상수")
    p.add_argument("--timeout", type=int, default=120, help="요청 타임아웃(초)")

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
    p.add_argument(
        "--doc-type", action="append", default=[], help="doc_type 필터 (복수 가능)"
    )
    p.add_argument(
        "--law-name", action="append", default=[], help="law_name 필터 (복수 가능)"
    )

    p.add_argument(
        "--max-content-chars", type=int, default=700, help="문서당 최대 글자 수"
    )
    p.add_argument(
        "--max-total-chars", type=int, default=2400, help="전체 최대 글자 수"
    )
    p.add_argument("--min-law-contexts", type=int, default=1, help="최소 law 문서 수")
    p.add_argument(
        "--enforce-min-law-contexts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="min_law_contexts 미충족 시 law 문서를 강제 보강 (기본: on)",
    )
    p.add_argument(
        "--auto-law-boost",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="규범형 질의일 때 law 문서 점수 자동 가산 (기본: on)",
    )
    p.add_argument(
        "--law-boost-score", type=float, default=0.003, help="law score 가산치"
    )

    p.add_argument(
        "--system-prompt",
        default=DEFAULT_ANSWER_BASELINE_PROMPT,
        help="생성용 시스템 프롬프트",
    )
    p.add_argument(
        "--llm-url", default="", help=f"기본: {DEFAULT_CHAT_COMPLETIONS_URL}"
    )
    p.add_argument(
        "--llm-provider",
        default="",
        choices=["openai_compat", "gemini"],
        help="LLM provider (기본: LLM_PROVIDER 또는 openai_compat)",
    )
    p.add_argument("--llm-model", default="", help=f"기본: {DEFAULT_MODEL}")
    p.add_argument(
        "--llm-api-key", default="", help="기본: LLM_API_KEY 또는 OPENAI_API_KEY"
    )
    p.add_argument(
        "--llm-max-input-chars",
        type=int,
        default=12000,
        help="LLM 입력 프롬프트 최대 문자 수 (토큰 초과 방지)",
    )
    p.add_argument(
        "--llm-max-tokens", type=int, default=4096, help="LLM 최대 생성 토큰"
    )
    p.add_argument("--llm-temperature", type=float, default=0.2, help="LLM 생성 온도")

    p.add_argument(
        "--snippet-max-chars",
        type=int,
        default=200,
        help="retrieved_docs.snippet 최대 글자 수",
    )
    p.add_argument(
        "--no-question",
        action="store_false",
        dest="include_question",
        help="JSON 출력에서 question 필드 제외",
    )
    p.add_argument("--text", action="store_true", help="디버그용 텍스트 출력")
    p.add_argument("--stream", action="store_true", help="LLM 답변을 스트리밍으로 출력")
    return p.parse_args()


def _run_for_question(args: argparse.Namespace, question: str) -> int:
    question = question.strip()
    if not question:
        raise SystemExit("[ERROR] 질문이 비어 있습니다.")

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
    candidate_k = max(args.top_k, args.candidate_k)

    try:
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
    except RetrievalError as exc:
        raise SystemExit(f"[ERROR] 검색 실패: {exc}") from exc

    rrf_rows_all = fuse_rrf(qdrant_rows, bm25_rows, rrf_k=args.rrf_k, top_k=candidate_k)
    rrf_rows_all = _apply_law_boost(
        rrf_rows_all,
        question=question,
        enabled=args.auto_law_boost,
        law_boost_score=args.law_boost_score,
    )

    llm_rows, law_context_status, law_context_added = _select_rows_with_law_policy(
        rows=rrf_rows_all,
        top_k=args.top_k,
        min_law_contexts=args.min_law_contexts,
        enforce_min_law_contexts=args.enforce_min_law_contexts,
    )

    contexts = _build_llm_context_rows(
        llm_rows,
        max_content_chars=args.max_content_chars,
        max_total_chars=args.max_total_chars,
    )
    retrieved_context_text = _build_llm_context_text(
        question, contexts, law_context_added
    )

    llm_prompt = _build_user_prompt_with_limit(
        retrieved_context_text=retrieved_context_text,
        question=question,
        max_input_chars=args.llm_max_input_chars,
        law_context_status=law_context_status,
    )

    answer = ""
    if args.stream:
        chunks: list[str] = []
        try:
            for chunk in stream_answer(
                llm_prompt,
                system_prompt=args.system_prompt or None,
                provider=args.llm_provider or None,
                url=args.llm_url or None,
                model=args.llm_model or None,
                api_key=args.llm_api_key or None,
                timeout=args.timeout,
                max_tokens=args.llm_max_tokens,
                temperature=args.llm_temperature,
            ):
                chunks.append(chunk)
                if args.text:
                    print(chunk, end="", flush=True)
                else:
                    print(
                        json.dumps(
                            {"type": "answer_delta", "delta": chunk}, ensure_ascii=False
                        ),
                        flush=True,
                    )
        except RetrievalError as exc:
            raise SystemExit(f"[ERROR] LLM 생성 실패: {exc}") from exc
        answer = "".join(chunks).strip()
        if args.text:
            print()
    else:
        try:
            answer = generate_answer(
                llm_prompt,
                system_prompt=args.system_prompt or None,
                provider=args.llm_provider or None,
                url=args.llm_url or None,
                model=args.llm_model or None,
                api_key=args.llm_api_key or None,
                timeout=args.timeout,
                max_tokens=args.llm_max_tokens,
                temperature=args.llm_temperature,
            )
        except RetrievalError as exc:
            raise SystemExit(f"[ERROR] LLM 생성 실패: {exc}") from exc

    payload = _build_frontend_payload(
        question=question,
        answer=answer,
        retrieved_docs=llm_rows,
        snippet_max_chars=args.snippet_max_chars,
        include_question=args.include_question,
        law_context_status=law_context_status,
        law_context_added=law_context_added,
    )

    if args.text:
        if not args.stream:
            print("[ANSWER]")
            print(answer)
        return 0

    if args.stream:
        print(
            json.dumps({"type": "final", "data": payload}, ensure_ascii=False),
            flush=True,
        )
        return 0

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    args = parse_args()

    if args.interactive:
        initial_question = args.question.strip()
        if initial_question:
            _run_for_question(args, initial_question)

        while True:
            try:
                question = input("\n질문> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0

            if question.lower() in {"q", "quit", "exit"}:
                return 0
            if not question:
                continue
            _run_for_question(args, question)

    if not args.question.strip():
        raise SystemExit("[ERROR] --question 또는 --interactive 중 하나는 필요합니다.")

    return _run_for_question(args, args.question)


if __name__ == "__main__":
    raise SystemExit(main())
