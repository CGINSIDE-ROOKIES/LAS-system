#!/usr/bin/env python3
"""RAGAS 기반 RAG 파이프라인 평가 스크립트.

현재 측정 메트릭 (ground_truth 불필요):
  - answer_relevancy       : 답변이 질문에 관련 있는지
  - context_precision      : 검색 컨텍스트 순위가 적절한지 (LLM 판단, reference 불필요)

  # faithfulness (답변이 컨텍스트에 근거하는지)는 비용/시간 문제로 제외.
  # 필요 시 ragas.metrics.collections.Faithfulness 로 추가 가능.

사용법:
  cd apps/backend/rag
  python eval/run_eval.py [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import re  # noqa: E402

from rag_pipeline.env_config import load_backend_env  # noqa: E402
from rag_pipeline.generation.pipeline import RagPipeline  # noqa: E402
from rag_pipeline.observability.langfuse_client import score_trace  # noqa: E402

load_backend_env()

_ANSWERABLE_RE = re.compile(r'\n?\[ANSWERABLE:(yes|no)\]\s*$', re.IGNORECASE)


def _strip_answerable(answer: str) -> str:
    m = _ANSWERABLE_RE.search(answer)
    return answer[:m.start()].rstrip() if m else answer
from rag_pipeline.observability.tracing import get_trace_id, start_trace  # noqa: E402
from rag_pipeline.query_parser import QueryParser  # noqa: E402


# ── 파이프라인 실행 ────────────────────────────────────────────────────────────

def collect_pipeline_results(
    pipeline: RagPipeline,
    queries: list[dict],
    *,
    query_parser: QueryParser | None = None,
) -> list[dict]:
    results = []
    for i, row in enumerate(queries, 1):
        query = row["query"]
        print(f"[{i:2}/{len(queries)}] {query[:60]}", flush=True)

        # Query Parser 적용
        law_names: list[str] | None = None
        pipeline_intent: str | None = None
        parser_law_names = ""
        parser_intent = ""
        if query_parser is not None:
            parsed = query_parser.parse(query)
            pipeline_intent = parsed.intent
            parser_intent = parsed.intent or ""
            if not parsed.is_legal:
                print(f"  → parser: is_legal=false, 스킵")
                results.append({
                    "query": query,
                    "intent": row.get("intent", ""),
                    "expected_doc_type": row.get("expected_doc_type", ""),
                    "gold_law": row.get("gold_law", ""),
                    "gold_article": row.get("gold_article", ""),
                    "answer": "법률 무관 질문으로 스킵",
                    "contexts": [],
                    "retrieved_doc_types": [],
                    "law_context_status": "irrelevant",
                    "parser_law_names": "",
                    "parser_intent": parser_intent,
                })
                continue
            # API와 동일한 우선순위: law_names → suggested_laws → None
            law_names = parsed.law_names or parsed.suggested_laws or None
            parser_law_names = "|".join(law_names) if law_names else ""
            if law_names:
                print(f"  → parser: law_names={law_names}")

        trace = start_trace("eval_run", input={"question": query, "intent": row.get("intent", "")})
        trace_id = get_trace_id(trace)
        try:
            result = pipeline.run(
                query,
                law_names=law_names,
                intent=pipeline_intent,
                search_query=(parsed.normalized_query or None) if query_parser else None,
                hypothetical_doc=(parsed.hypothetical_doc or None) if query_parser else None,
                trace=trace,
            )
            retrieved_law_names = {doc.get("law_name", "") for doc in result.retrieved_docs}
            gold_law = row.get("gold_law", "")
            law_hit = int(bool(gold_law and gold_law in retrieved_law_names))
            results.append({
                "query": query,
                "intent": row.get("intent", ""),
                "expected_doc_type": row.get("expected_doc_type", ""),
                "gold_law": gold_law,
                "gold_article": row.get("gold_article", ""),
                "answer": _strip_answerable(result.answer),
                "contexts": [
                    doc["text"]
                    for doc in result.retrieved_docs
                    if doc.get("text")
                ],
                "retrieved_doc_types": [
                    doc["doc_type"] for doc in result.retrieved_docs
                ],
                "law_context_status": result.law_context_status,
                "parser_law_names": parser_law_names,
                "parser_intent": parser_intent,
                "law_hit": law_hit,
                "trace_id": trace_id,
            })
        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append({
                "query": query,
                "intent": row.get("intent", ""),
                "expected_doc_type": row.get("expected_doc_type", ""),
                "gold_law": row.get("gold_law", ""),
                "gold_article": row.get("gold_article", ""),
                "answer": f"ERROR: {exc}",
                "contexts": [],
                "retrieved_doc_types": [],
                "law_context_status": "error",
                "parser_law_names": parser_law_names,
                "parser_intent": parser_intent,
                "law_hit": None,
                "trace_id": trace_id,
            })
    return results


# ── RAGAS 평가 ────────────────────────────────────────────────────────────────

def run_ragas(results: list[dict], *, batch_size: int = 5, batch_sleep: float = 30.0) -> list[dict]:
    import time
    from openai import AsyncOpenAI, NotFoundError
    from ragas.cache import DiskCacheBackend
    from ragas.embeddings import OpenAIEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy
    from ragas.metrics.collections import ContextPrecisionWithoutReference
    from ragas.metrics.collections import Faithfulness

    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("LLM_API_KEY가 없습니다. apps/backend/.env를 확인하세요.")

    ragas_model = (
        os.getenv("RAGAS_MODEL", "").strip()
        or os.getenv("LLM_MODEL", "").strip()
        or "gpt-4o-mini"
    )
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    emb_model = os.getenv("RAGAS_EMBEDDING_MODEL", "").strip() or "text-embedding-3-small"

    cache = DiskCacheBackend(cache_dir=str(Path(__file__).parent.parent / "data/staging/.ragas_cache"))
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    ragas_llm = llm_factory(ragas_model, client=client, cache=cache, max_tokens=8192)
    ragas_emb = OpenAIEmbeddings(client, model=emb_model, cache=cache)

    from ragas.metrics.collections.answer_relevancy.util import (
        AnswerRelevanceInput, AnswerRelevanceOutput, AnswerRelevancePrompt,
    )

    class KoreanAnswerRelevancePrompt(AnswerRelevancePrompt):
        instruction = (
            "주어진 답변에서 질문을 생성하고, 답변이 불성실한지 여부를 판단하세요. "
            "답변이 모호하거나 회피적이면 noncommittal=1, 실질적인 내용이 있으면 noncommittal=0을 반환하세요."
        )
        examples = [
            (
                AnswerRelevanceInput(response="근로기준법에 따라 사용자는 근로자를 해고하려면 적어도 30일 전에 예고하여야 합니다."),
                AnswerRelevanceOutput(question="해고 예고 기간은 얼마나 되나요?", noncommittal=0),
            ),
            (
                AnswerRelevanceInput(response="연장근로는 당사자 합의 시 1주에 12시간을 한도로 허용됩니다."),
                AnswerRelevanceOutput(question="연장근로는 최대 몇 시간까지 가능한가요?", noncommittal=0),
            ),
            (
                AnswerRelevanceInput(response="잘 모르겠습니다. 법령마다 다를 수 있어 확인이 필요합니다."),
                AnswerRelevanceOutput(question="관련 법령의 규정이 어떻게 되나요?", noncommittal=1),
            ),
        ]

    relevancy_m = AnswerRelevancy(llm=ragas_llm, embeddings=ragas_emb)
    relevancy_m.prompt = KoreanAnswerRelevancePrompt()
    precision_m = ContextPrecisionWithoutReference(llm=ragas_llm)
    faithfulness_m = Faithfulness(llm=ragas_llm)

    valid = [r for r in results if r["contexts"]]
    skipped = len(results) - len(valid)
    if skipped:
        print(f"  컨텍스트 없는 항목 {skipped}개 제외")

    if not valid:
        print("  평가 가능한 결과 없음 — 파이프라인 에러를 먼저 확인하세요.")
        for row in results:
            row.setdefault("answer_relevancy", None)
            row.setdefault("context_precision", None)
        return results

    # batch_score 입력 포맷: user_input / response / retrieved_contexts
    def to_inputs(batch: list[dict]) -> list[dict]:
        return [
            {
                "user_input": r["query"],
                "response": r["answer"],
                "retrieved_contexts": r["contexts"],
            }
            for r in batch
        ]

    # RPM 초과 방지: batch_size개씩 나눠서 평가
    for batch_start in range(0, len(valid), batch_size):
        batch = valid[batch_start: batch_start + batch_size]
        batch_end = min(batch_start + batch_size, len(valid))
        print(f"  배치 [{batch_start + 1}~{batch_end}/{len(valid)}] 평가 중...", flush=True)

        inputs = to_inputs(batch)
        try:
            rel_scores = relevancy_m.batch_score(
                [{"user_input": i["user_input"], "response": i["response"]} for i in inputs]
            )
            prec_scores = precision_m.batch_score(inputs)
        except NotFoundError as exc:
            raise RuntimeError(
                "RAGAS 평가 모델을 찾지 못했습니다. "
                f"현재 모델: {ragas_model}. "
                "RAGAS_MODEL 또는 LLM_MODEL을 사용 가능한 모델로 바꿔주세요."
            ) from exc

        for j, row in enumerate(batch):
            row["answer_relevancy"]  = round(float(rel_scores[j].value), 4)
            row["context_precision"] = round(float(prec_scores[j].value), 4)

        if batch_end < len(valid):
            print(f"  Rate limit 대기 {batch_sleep:.0f}s...", flush=True)
            time.sleep(batch_sleep)

    for row in results:
        row.setdefault("answer_relevancy", None)
        row.setdefault("context_precision", None)
        row.setdefault("law_hit", None)

    # faithfulness: answer_relevancy < 0.6인 저점수 쿼리만 선택적 실행
    low_quality = [r for r in valid if r.get("answer_relevancy") is not None and r["answer_relevancy"] < 0.6]
    if low_quality:
        print(f"  faithfulness 평가: {len(low_quality)}건 (answer_relevancy < 0.6)", flush=True)
        try:
            if valid:
                print(f"  Rate limit 대기 {batch_sleep:.0f}s...", flush=True)
                time.sleep(batch_sleep)
            faith_scores = faithfulness_m.batch_score(to_inputs(low_quality))
            for j, row in enumerate(low_quality):
                row["faithfulness"] = round(float(faith_scores[j].value), 4)
        except NotFoundError as exc:
            raise RuntimeError(
                "RAGAS 평가 모델을 찾지 못했습니다. "
                f"현재 모델: {ragas_model}. "
                "RAGAS_MODEL 또는 LLM_MODEL을 사용 가능한 모델로 바꿔주세요."
            ) from exc
    else:
        print("  faithfulness 평가 대상 없음 (모든 answer_relevancy ≥ 0.6)")

    for row in results:
        row.setdefault("faithfulness", None)

    return results


# ── Langfuse score push ───────────────────────────────────────────────────────

def push_langfuse_scores(results: list[dict]) -> None:
    """ragas 점수와 law_hit을 Langfuse trace에 기록한다."""
    pushed = 0
    for row in results:
        trace_id = row.get("trace_id")
        if not trace_id:
            continue
        low_rel = row.get("answer_relevancy") is not None and row["answer_relevancy"] < 0.5
        if row.get("answer_relevancy") is not None:
            comment = row["query"][:100] if low_rel else None
            score_trace(trace_id, "answer_relevancy", row["answer_relevancy"], comment=comment)
        if row.get("context_precision") is not None:
            score_trace(trace_id, "context_precision", row["context_precision"])
        if row.get("faithfulness") is not None:
            low_faith = row["faithfulness"] < 0.5
            comment = row["query"][:100] if low_faith else None
            score_trace(trace_id, "faithfulness", row["faithfulness"], comment=comment)
        if row.get("law_hit") is not None:
            score_trace(trace_id, "law_hit", float(row["law_hit"]))
        pushed += 1
    print(f"  Langfuse score push 완료: {pushed}건")


# ── 결과 저장 ─────────────────────────────────────────────────────────────────

FIELDNAMES = [
    "query", "intent", "expected_doc_type", "gold_law", "gold_article",
    "law_context_status",
    "answer_relevancy", "context_precision", "faithfulness", "law_hit",
    "retrieved_doc_types", "parser_law_names", "parser_intent", "answer", "trace_id",
]


def save_results(results: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"eval_{ts}.csv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            out = dict(row)
            out["retrieved_doc_types"] = "|".join(out.get("retrieved_doc_types") or [])
            writer.writerow(out)

    return out_path


# ── 요약 출력 ─────────────────────────────────────────────────────────────────

def _avg(rows: list[dict], key: str) -> float:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0


def print_summary(results: list[dict]) -> None:
    scored = [r for r in results if r.get("answer_relevancy") is not None]

    print("\n" + "=" * 50)
    print("전체 평균")
    print("=" * 50)
    if not scored:
        print("  측정 가능한 결과 없음")
        return

    for metric in ("answer_relevancy", "context_precision"):
        print(f"  {metric:<26} {_avg(scored, metric):.3f}  (n={len(scored)})")

    faith_rows = [r for r in results if r.get("faithfulness") is not None]
    if faith_rows:
        print(f"  {'faithfulness':<26} {_avg(faith_rows, 'faithfulness'):.3f}  (n={len(faith_rows)}, 저점수 대상)")

    law_hit_rows = [r for r in results if r.get("law_hit") is not None and r.get("gold_law")]
    if law_hit_rows:
        hit_rate = sum(r["law_hit"] for r in law_hit_rows) / len(law_hit_rows)
        print(f"  {'law_hit':<26} {hit_rate:.3f}  (n={len(law_hit_rows)})")

    # intent별
    intents = sorted({r["intent"] for r in scored})
    if len(intents) > 1:
        print("\nIntent별 평균")
        print("-" * 50)
        for intent in intents:
            group = [r for r in scored if r["intent"] == intent]
            rel  = _avg(group, "answer_relevancy")
            prec = _avg(group, "context_precision")
            print(f"  [{intent:<12}] n={len(group):2}  "
                  f"rel={rel:.3f}  prec={prec:.3f}")
            # faithfulness 메트릭은 비용/시간 문제로 제외. 추후 추가 가능.

    # law_context_status 분포
    print("\nlaw_context_status")
    print("-" * 50)
    for status, cnt in Counter(r["law_context_status"] for r in results).most_common():
        print(f"  {status:<14} {cnt}")

    # 저점수 쿼리
    low = sorted(
        [r for r in scored if r.get("answer_relevancy") is not None and r["answer_relevancy"] < 0.5],
        key=lambda r: r["answer_relevancy"],
    )
    if low:
        print(f"\n낮은 answer_relevancy (<0.5)  {len(low)}건")
        print("-" * 50)
        for r in low:
            print(f"  {r['answer_relevancy']:.2f}  [{r['intent']:<12}]  {r['query'][:55]}")


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main() -> None:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--limit", type=int, default=0, help="평가할 쿼리 수 제한 (0=전체)")
    arg_parser.add_argument("--no-parser", action="store_true", help="Query Parser 미적용 (baseline 측정용)")
    args = arg_parser.parse_args()

    eval_csv = Path(__file__).parent.parent / "data/staging/eval_set.csv"
    out_dir  = Path(__file__).parent.parent / "data/staging/eval_results"

    with open(eval_csv, encoding="utf-8") as f:
        queries = list(csv.DictReader(f))

    if args.limit:
        queries = queries[: args.limit]

    mode = "baseline" if args.no_parser else "parser 적용"
    print(f"평가 쿼리: {len(queries)}개  [{mode}]")

    pipeline = RagPipeline.from_env()
    query_parser = None if args.no_parser else QueryParser.from_env()
    print("파이프라인 초기화 완료\n")

    print("=== Step 1. 파이프라인 실행 ===")
    results = collect_pipeline_results(pipeline, queries, query_parser=query_parser)

    print("\n=== Step 2. RAGAS 평가 ===")
    results = run_ragas(results)

    print("\n=== Step 3. Langfuse score push ===")
    push_langfuse_scores(results)

    out_path = save_results(results, out_dir)
    print(f"\n결과 저장: {out_path}")

    print_summary(results)


if __name__ == "__main__":
    main()
