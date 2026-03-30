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

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

from rag_pipeline.generation.pipeline import RagPipeline  # noqa: E402


# ── 파이프라인 실행 ────────────────────────────────────────────────────────────

def collect_pipeline_results(
    pipeline: RagPipeline,
    queries: list[dict],
) -> list[dict]:
    results = []
    for i, row in enumerate(queries, 1):
        query = row["query"]
        print(f"[{i:2}/{len(queries)}] {query[:60]}", flush=True)
        try:
            result = pipeline.run(query)
            results.append({
                "query": query,
                "intent": row.get("intent", ""),
                "expected_doc_type": row.get("expected_doc_type", ""),
                "gold_law": row.get("gold_law", ""),
                "gold_article": row.get("gold_article", ""),
                "answer": result.answer,
                "contexts": [
                    doc["text"]
                    for doc in result.retrieved_docs
                    if doc.get("text")
                ],
                "retrieved_doc_types": [
                    doc["doc_type"] for doc in result.retrieved_docs
                ],
                "law_context_status": result.law_context_status,
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
            })
    return results


# ── RAGAS 평가 ────────────────────────────────────────────────────────────────

def run_ragas(results: list[dict], *, batch_size: int = 5, batch_sleep: float = 30.0) -> list[dict]:
    import time
    from openai import AsyncOpenAI, NotFoundError
    from ragas.cache import DiskCacheBackend
    from ragas.embeddings import GoogleEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy
    from ragas.metrics.collections import ContextPrecisionWithoutReference

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 없습니다. apps/backend/rag/.env를 확인하세요.")

    ragas_model = (
        os.getenv("RAGAS_GEMINI_MODEL", "").strip()
        or os.getenv("GEMINI_MODEL", "").strip()
        or "gemini-flash-latest"
    )
    cache = DiskCacheBackend(cache_dir=str(Path(__file__).parent.parent / "data/staging/.ragas_cache"))
    # Gemini의 OpenAI 호환 엔드포인트 사용
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    ragas_llm = llm_factory(ragas_model, client=client, cache=cache, max_tokens=8192)
    ragas_emb = GoogleEmbeddings(model="gemini-embedding-001", cache=cache)

    relevancy_m = AnswerRelevancy(llm=ragas_llm, embeddings=ragas_emb)
    precision_m = ContextPrecisionWithoutReference(llm=ragas_llm)

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
                "RAGAS_GEMINI_MODEL 또는 GEMINI_MODEL을 사용 가능한 모델로 바꿔주세요."
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

    return results


# ── 결과 저장 ─────────────────────────────────────────────────────────────────

FIELDNAMES = [
    "query", "intent", "expected_doc_type", "gold_law", "gold_article",
    "law_context_status",
    "answer_relevancy", "context_precision",
    "retrieved_doc_types", "answer",
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="평가할 쿼리 수 제한 (0=전체)")
    args = parser.parse_args()

    eval_csv = Path(__file__).parent.parent / "data/staging/eval_set.csv"
    out_dir  = Path(__file__).parent.parent / "data/staging/eval_results"

    with open(eval_csv, encoding="utf-8") as f:
        queries = list(csv.DictReader(f))

    if args.limit:
        queries = queries[: args.limit]

    print(f"평가 쿼리: {len(queries)}개")

    pipeline = RagPipeline.from_env()
    print("파이프라인 초기화 완료\n")

    print("=== Step 1. 파이프라인 실행 ===")
    results = collect_pipeline_results(pipeline, queries)

    print("\n=== Step 2. RAGAS 평가 ===")
    results = run_ragas(results)

    out_path = save_results(results, out_dir)
    print(f"\n결과 저장: {out_path}")

    print_summary(results)


if __name__ == "__main__":
    main()
