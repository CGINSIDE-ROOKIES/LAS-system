"""실험1 추가: NL2Cypher 방식 B 멀티 모델 비교.

방식 B (LLM 자유 Cypher 생성)를 여러 LLM으로 실행해
정확도 / 레이턴시 / 토큰 비용을 비교한다.

실행:
  uv run --project apps/backend/legal-pipeline python scripts/experiment1_model_compare.py

환경변수:
  GEMINI_API_KEY   — Gemini API 키
  OPENAI_API_KEY   — OpenAI API 키 (gpt-4o-mini, gpt-4o)
  NEO4J_URI        — Neo4j 접속 URI (기본: bolt://localhost:7687)
  NEO4J_USER       — Neo4j 사용자
  NEO4J_PASSWORD   — Neo4j 비밀번호
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "apps/backend/rag"))

from dotenv import load_dotenv

load_dotenv(override=True)


# ── 테스트셋 (experiment1과 동일) ─────────────────────────────────────────────

@dataclass
class TestCase:
    query: str
    category: str
    expected_law_name: str
    expected_relation_type: str
    expected_result_contains: list[str] = field(default_factory=list)


TEST_CASES: list[TestCase] = [
    TestCase("근로기준법의 하위법령은 무엇인가요?", "child_law", "근로기준법", "child_law", ["근로기준법 시행령"]),
    TestCase("산업안전보건법 시행령과 시행규칙을 알려주세요.", "child_law", "산업안전보건법", "child_law", ["산업안전보건법 시행령"]),
    TestCase("하도급거래 공정화에 관한 법률의 하위 법령 목록", "child_law", "하도급거래 공정화에 관한 법률", "child_law", []),
    TestCase("근로기준법이 위임하는 법령은 어디인가요?", "delegation", "근로기준법", "delegation", []),
    TestCase("산업안전보건법의 위임 관계를 보여주세요.", "delegation", "산업안전보건법", "delegation", []),
    TestCase("최저임금법이 시행령에 위임하는 내용", "delegation", "최저임금법", "delegation", []),
    TestCase("근로기준법이 참조하는 다른 법령은 무엇인가요?", "reference", "근로기준법", "reference", []),
    TestCase("산업안전보건법이 참조하는 법령 목록", "reference", "산업안전보건법", "reference", []),
    TestCase("하도급거래 공정화에 관한 법률 제2조가 참조하는 조문", "reference", "하도급거래 공정화에 관한 법률", "reference", []),
    TestCase("최저임금법이 다른 법령을 참조하는 경우", "reference", "최저임금법", "reference", []),
]


# ── 모델 설정 ──────────────────────────────────────────────────────────────────

@dataclass
class ModelConfig:
    label: str       # 결과 표시용 이름
    provider: str    # "gemini" | "openai_compat"
    model: str       # 모델 ID
    url: str         # API endpoint URL
    api_key: str     # API 키


def build_model_configs() -> list[ModelConfig]:
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()

    configs: list[ModelConfig] = []

    if gemini_key:
        configs.append(ModelConfig(
            label=f"gemini/{gemini_model}",
            provider="gemini",
            model=gemini_model,
            url=f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent",
            api_key=gemini_key,
        ))
    else:
        print("[WARN] GEMINI_API_KEY 없음 — gemini 모델 건너뜀")

    if openai_key:
        openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        for model_id in ["gpt-4o-mini"]:
            configs.append(ModelConfig(
                label=f"openai/{model_id}",
                provider="openai_compat",
                model=model_id,
                url=f"{openai_base}/chat/completions",
                api_key=openai_key,
            ))
    else:
        print("[WARN] OPENAI_API_KEY 없음 — OpenAI 모델 건너뜀")

    return configs


# ── 방식 B 시스템 프롬프트 (experiment1과 동일) ───────────────────────────────

_SYSTEM_PROMPT_B = """\
당신은 Neo4j Cypher 전문가입니다.
아래 스키마에서 자연어 질의에 맞는 Cypher를 생성하세요.

노드: Law(law_uid, law_name), Article(article_uid, article_no)
관계:
  (Law)-[:HAS_ARTICLE]->(Article)
  (Law)-[:HAS_CHILD_LAW]->(Law)
  (Law)-[:DELEGATES_TO_LAW]->(Law)
  (Law)-[:REFERS_TO_LAW]->(Law)
  (Article)-[:REFERS_TO_ARTICLE]->(Article)

반드시 JSON만 출력하세요:
{{"cypher": "...", "params": {{"law_name": "..."}}}}
"""

_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# ── 결과 데이터 클래스 ─────────────────────────────────────────────────────────

@dataclass
class RunResult:
    model_label: str
    query: str
    category: str
    law_name_correct: bool
    relation_type_correct: bool
    results_count: int
    keyword_hit: bool
    latency_ms: float
    input_tokens: int
    output_tokens: int
    error: str | None


# ── 실행 함수 ──────────────────────────────────────────────────────────────────

def run_b_with_model(tc: TestCase, neo4j_client: Any, cfg: ModelConfig) -> RunResult:
    from rag_pipeline.generation.llm_client import generate_answer

    t0 = time.perf_counter()
    error = None
    results: list[dict] = []
    got_law_name: str | None = None
    got_relation_type: str | None = None
    input_tokens = 0
    output_tokens = 0

    try:
        raw_text, usage = generate_answer(
            f"질문: {tc.query}\n출력:",
            provider=cfg.provider,
            url=cfg.url,
            model=cfg.model,
            api_key=cfg.api_key,
            timeout=20,
            max_tokens=2048,
            temperature=0.0,
            system_prompt=_SYSTEM_PROMPT_B,
        )
        if usage:
            input_tokens = usage.get("input", 0) or usage.get("prompt_tokens", 0) or usage.get("promptTokenCount", 0)
            output_tokens = usage.get("output", 0) or usage.get("completion_tokens", 0) or usage.get("candidatesTokenCount", 0)

        # JSON 파싱
        m = _JSON_RE.search(raw_text)
        raw_json = m.group(1) if m else raw_text
        decoder = json.JSONDecoder()
        for i, ch in enumerate(raw_json):
            if ch == "{":
                try:
                    data, _ = decoder.raw_decode(raw_json[i:])
                    break
                except Exception:
                    continue
        else:
            raise ValueError(f"JSON 파싱 실패: {raw_text!r}")

        cypher = data.get("cypher", "")
        params = data.get("params", {})
        got_law_name = params.get("law_name")

        cu = cypher.upper()
        if "HAS_CHILD_LAW" in cu:
            got_relation_type = "child_law"
        elif "DELEGATES_TO_LAW" in cu:
            got_relation_type = "delegation"
        elif "REFERS_TO" in cu:
            got_relation_type = "reference"
        elif "HAS_ARTICLE" in cu:
            got_relation_type = "structure"

        results = neo4j_client.run_query(cypher, params)

    except Exception as exc:
        error = str(exc)

    latency_ms = (time.perf_counter() - t0) * 1000
    keyword_hit = all(kw in json.dumps(results, ensure_ascii=False) for kw in tc.expected_result_contains) if tc.expected_result_contains else True

    return RunResult(
        model_label=cfg.label,
        query=tc.query,
        category=tc.category,
        law_name_correct=got_law_name == tc.expected_law_name,
        relation_type_correct=got_relation_type == tc.expected_relation_type,
        results_count=len(results),
        keyword_hit=keyword_hit,
        latency_ms=round(latency_ms, 1),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error=error,
    )


# ── 요약 출력 ──────────────────────────────────────────────────────────────────

def _print_summary(all_results: list[RunResult], configs: list[ModelConfig]) -> None:
    print("\n" + "=" * 80)
    print("멀티 모델 비교 결과 (방식 B — LLM 자유 Cypher 생성)")
    print("=" * 80)
    print(f"{'모델':<28} {'law_name':>10} {'rel_type':>10} {'결과수avg':>10} {'레이턴시avg':>12} {'토큰(in/out)':>14} {'에러'}")
    print("-" * 80)

    for cfg in configs:
        rows = [r for r in all_results if r.model_label == cfg.label]
        if not rows:
            continue
        n = len(rows)
        law_acc = sum(1 for r in rows if r.law_name_correct) / n
        rel_acc = sum(1 for r in rows if r.relation_type_correct) / n
        avg_cnt = sum(r.results_count for r in rows) / n
        avg_lat = sum(r.latency_ms for r in rows) / n
        total_in = sum(r.input_tokens for r in rows)
        total_out = sum(r.output_tokens for r in rows)
        errs = sum(1 for r in rows if r.error)
        print(
            f"{cfg.label:<28} {law_acc:>9.0%} {rel_acc:>10.0%} {avg_cnt:>10.1f} "
            f"{avg_lat:>10.0f}ms {total_in:>7}in/{total_out:<5}out {errs:>4}"
        )

    print("=" * 80)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    configs = build_model_configs()
    if not configs:
        print("[ERROR] 사용 가능한 모델 설정이 없습니다. API 키를 확인하세요.")
        sys.exit(1)

    from rag_pipeline.graph.neo4j_client import Neo4jClient
    neo4j = Neo4jClient.from_env()

    all_results: list[RunResult] = []

    print(f"멀티 모델 비교 시작: {len(TEST_CASES)}개 질의 × {len(configs)}개 모델\n")
    print("모델:", [c.label for c in configs])
    print()

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"[{i:02d}/{len(TEST_CASES)}] {tc.query[:50]}")
        for cfg in configs:
            r = run_b_with_model(tc, neo4j, cfg)
            status = "OK" if (r.law_name_correct and r.relation_type_correct and not r.error) else "FAIL"
            print(
                f"  {cfg.label:<28} [{status}] law={r.law_name_correct} rel={r.relation_type_correct} "
                f"cnt={r.results_count} {r.latency_ms:.0f}ms"
                + (f" ERR={r.error[:50]}" if r.error else "")
            )
            all_results.append(r)
        print()

    _print_summary(all_results, configs)

    out_dir = Path(__file__).parent.parent / "data" / "experiment_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"experiment1_model_compare_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in all_results], f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {out_path}")
    neo4j.close()


if __name__ == "__main__":
    main()
