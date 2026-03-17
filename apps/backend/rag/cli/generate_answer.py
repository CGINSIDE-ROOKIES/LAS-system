#!/usr/bin/env python3
"""검색 결과 컨텍스트를 기반으로 LLM 최종 답변을 생성하는 전용 엔트리포인트.

사용 예시:
  uv run python scripts/generate_answer.py --question "연장근로 최대 시간은?"
  uv run python scripts/generate_answer.py --question "..." --json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

# Ensure local CLI modules are importable regardless of invocation cwd.
CLI_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from query_all_retrieval import (
    DEFAULT_SYSTEM_PROMPT,
    _apply_law_boost,
    _build_llm_context_rows,
    _build_llm_context_text,
    _select_llm_rows,
)
from query_hybrid_rrf import fuse_rrf
from retrieval_common import (
    DEFAULT_EMBEDDING_MODEL,
    RetrievalError,
    http_json,
    require_env_or_arg,
    search_bm25,
    search_qdrant,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="검색 + 컨텍스트 + LLM 생성 전용 실행기")

    p.add_argument("--question", required=True, help="질문 텍스트")
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
        "--system-prompt", default=DEFAULT_SYSTEM_PROMPT, help="생성용 시스템 프롬프트"
    )
    p.add_argument(
        "--max-content-chars", type=int, default=1200, help="문서당 최대 글자 수"
    )
    p.add_argument(
        "--max-total-chars", type=int, default=6000, help="전체 최대 글자 수"
    )
    p.add_argument("--min-law-contexts", type=int, default=1, help="최소 law 문서 수")

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
        "--llm-base-url", default="", help="기본: LLM_BASE_URL (OpenAI 호환)"
    )
    p.add_argument(
        "--llm-api-key", default="", help="기본: LLM_API_KEY 또는 OPENAI_API_KEY"
    )
    p.add_argument("--llm-model", default="", help="기본: LLM_MODEL")
    p.add_argument("--llm-temperature", type=float, default=0.1, help="LLM temperature")
    p.add_argument("--llm-max-tokens", type=int, default=700, help="LLM 최대 생성 토큰")

    p.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    return p.parse_args()


def _generate_with_openai_compatible(
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    system_prompt: str,
    user_question: str,
    retrieved_context_text: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "다음 컨텍스트를 근거로 질문에 답변하세요.\n\n"
                    f"{retrieved_context_text}\n\n"
                    f"[최종 질문]\n{user_question}"
                ),
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    url = f"{base_url.rstrip('/')}/chat/completions"
    res = http_json("POST", url, payload, headers, timeout)
    choices = res.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RetrievalError("LLM 응답에 choices가 없습니다.")

    first = choices[0]
    if not isinstance(first, dict):
        raise RetrievalError("LLM 응답 choices[0] 형식이 올바르지 않습니다.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RetrievalError("LLM 응답에 message가 없습니다.")

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RetrievalError("LLM 응답에 content가 없습니다.")
    return content.strip()


def main() -> int:
    args = parse_args()
    question = args.question.strip()

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
    llm_base_url = require_env_or_arg(args.llm_base_url, "LLM_BASE_URL")
    llm_model = require_env_or_arg(args.llm_model, "LLM_MODEL")
    llm_api_key = (
        (args.llm_api_key or "").strip()
        or os.getenv("LLM_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
        or None
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

    rrf_rows = fuse_rrf(qdrant_rows, bm25_rows, rrf_k=args.rrf_k, top_k=args.top_k)
    rrf_rows = _apply_law_boost(
        rrf_rows,
        question=question,
        enabled=args.auto_law_boost,
        law_boost_score=args.law_boost_score,
    )[: max(1, args.top_k)]

    llm_rows, law_context_added = _select_llm_rows(
        rrf_rows,
        top_k=args.top_k,
        min_law_contexts=args.min_law_contexts,
    )
    contexts = _build_llm_context_rows(
        llm_rows,
        max_content_chars=args.max_content_chars,
        max_total_chars=args.max_total_chars,
    )
    retrieved_context_text = _build_llm_context_text(
        question,
        contexts,
        law_context_added,
    )

    try:
        answer = _generate_with_openai_compatible(
            base_url=llm_base_url,
            api_key=llm_api_key,
            model=llm_model,
            system_prompt=args.system_prompt,
            user_question=question,
            retrieved_context_text=retrieved_context_text,
            temperature=args.llm_temperature,
            max_tokens=args.llm_max_tokens,
            timeout=args.timeout,
        )
    except RetrievalError as exc:
        raise SystemExit(f"[ERROR] LLM 생성 실패: {exc}") from exc

    if args.json:
        print(
            json.dumps(
                {
                    "question": question,
                    "top_k": args.top_k,
                    "candidate_k": candidate_k,
                    "rrf_k": args.rrf_k,
                    "law_context_added": law_context_added,
                    "contexts": contexts,
                    "answer": answer,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("[ANSWER]")
    print(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
