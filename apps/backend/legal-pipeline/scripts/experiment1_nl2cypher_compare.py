"""실험1: NL2Cypher 방식 비교.

방식 A (Template) vs 방식 B (LLM 자유 생성) vs 방식 C (ReAct Agent)
10개 법령 구조 질의로 정답 성공률 / 레이턴시 / 토큰 비용을 비교한다.

실행:
  uv run --project apps/backend/legal-pipeline python scripts/experiment1_nl2cypher_compare.py

환경변수:
  GEMINI_API_KEY  — Gemini API 키 (방식 A, B, C 공통)
  NEO4J_URI       — Neo4j 접속 URI (기본: bolt://localhost:7687)
  NEO4J_USER      — Neo4j 사용자
  NEO4J_PASSWORD  — Neo4j 비밀번호
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ── project root를 sys.path에 추가 ────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "apps/backend/rag"))

from dotenv import load_dotenv

load_dotenv(override=True)


# ── 테스트셋 정의 ──────────────────────────────────────────────────────────────

@dataclass
class TestCase:
    query: str
    category: str  # "child_law" | "delegation" | "reference"
    expected_law_name: str
    expected_relation_type: str
    expected_result_contains: list[str] = field(default_factory=list)  # 결과에 포함돼야 할 키워드


TEST_CASES: list[TestCase] = [
    # 하위법령 3건
    TestCase(
        query="근로기준법의 하위법령은 무엇인가요?",
        category="child_law",
        expected_law_name="근로기준법",
        expected_relation_type="child_law",
        expected_result_contains=["근로기준법 시행령"],
    ),
    TestCase(
        query="산업안전보건법 시행령과 시행규칙을 알려주세요.",
        category="child_law",
        expected_law_name="산업안전보건법",
        expected_relation_type="child_law",
        expected_result_contains=["산업안전보건법 시행령"],
    ),
    TestCase(
        query="하도급거래 공정화에 관한 법률의 하위 법령 목록",
        category="child_law",
        expected_law_name="하도급거래 공정화에 관한 법률",
        expected_relation_type="child_law",
        expected_result_contains=[],
    ),
    # 위임 관계 3건
    TestCase(
        query="근로기준법이 위임하는 법령은 어디인가요?",
        category="delegation",
        expected_law_name="근로기준법",
        expected_relation_type="delegation",
        expected_result_contains=[],
    ),
    TestCase(
        query="산업안전보건법의 위임 관계를 보여주세요.",
        category="delegation",
        expected_law_name="산업안전보건법",
        expected_relation_type="delegation",
        expected_result_contains=[],
    ),
    TestCase(
        query="최저임금법이 시행령에 위임하는 내용",
        category="delegation",
        expected_law_name="최저임금법",
        expected_relation_type="delegation",
        expected_result_contains=[],
    ),
    # 참조 관계 4건
    TestCase(
        query="근로기준법이 참조하는 다른 법령은 무엇인가요?",
        category="reference",
        expected_law_name="근로기준법",
        expected_relation_type="reference",
        expected_result_contains=[],
    ),
    TestCase(
        query="산업안전보건법이 참조하는 법령 목록",
        category="reference",
        expected_law_name="산업안전보건법",
        expected_relation_type="reference",
        expected_result_contains=[],
    ),
    TestCase(
        query="하도급거래 공정화에 관한 법률 제2조가 참조하는 조문",
        category="reference",
        expected_law_name="하도급거래 공정화에 관한 법률",
        expected_relation_type="reference",
        expected_result_contains=[],
    ),
    TestCase(
        query="최저임금법이 다른 법령을 참조하는 경우",
        category="reference",
        expected_law_name="최저임금법",
        expected_relation_type="reference",
        expected_result_contains=[],
    ),
]


# ── 결과 데이터 클래스 ─────────────────────────────────────────────────────────

@dataclass
class RunResult:
    method: str  # "A_template" | "B_llm_free" | "C_react_agent"
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


# ── 방식 A: Template (CypherPlanner) ──────────────────────────────────────────

def run_method_a(tc: TestCase, neo4j_client: Any, planner: Any) -> RunResult:
    """방식 A: W1 구현의 CypherPlanner 사용."""
    t0 = time.perf_counter()
    error = None
    results: list[dict] = []
    got_law_name: str | None = None
    got_relation_type: str | None = None

    try:
        plan = planner.plan(tc.query)
        if plan is None:
            error = "plan() returned None"
        else:
            got_law_name = plan.slots.law_name
            got_relation_type = plan.relation_type
            results = neo4j_client.run_query(plan.cypher, plan.params)
    except Exception as exc:
        error = str(exc)

    latency_ms = (time.perf_counter() - t0) * 1000

    keyword_hit = _check_keyword_hit(results, tc.expected_result_contains)

    return RunResult(
        method="A_template",
        query=tc.query,
        category=tc.category,
        law_name_correct=got_law_name == tc.expected_law_name,
        relation_type_correct=got_relation_type == tc.expected_relation_type,
        results_count=len(results),
        keyword_hit=keyword_hit,
        latency_ms=round(latency_ms, 1),
        input_tokens=0,  # 방식 A는 슬롯 추출 LLM 토큰 (별도 추적 어려움)
        output_tokens=0,
        error=error,
    )


# ── 방식 B: LLM 자유 생성 ─────────────────────────────────────────────────────

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


def run_method_b(tc: TestCase, neo4j_client: Any, api_key: str) -> RunResult:
    """방식 B: LLM에게 Cypher 직접 생성 요청."""
    from rag_pipeline.generation.llm_client import generate_answer
    import re

    _JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

    t0 = time.perf_counter()
    error = None
    results: list[dict] = []
    got_law_name: str | None = None
    got_relation_type: str | None = None
    input_tokens = 0
    output_tokens = 0

    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    try:
        raw_text, usage = generate_answer(
            f"질문: {tc.query}\n출력:",
            provider="gemini",
            url=url,
            model=model,
            api_key=api_key,
            timeout=15,
            max_tokens=2048,
            temperature=0.0,
            system_prompt=_SYSTEM_PROMPT_B,
        )
        if usage:
            input_tokens = usage.get("input", 0)
            output_tokens = usage.get("output", 0)

        # JSON 파싱
        m = _JSON_RE.search(raw_text)
        raw_json = m.group(1) if m else raw_text
        decoder = __import__("json").JSONDecoder()
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

        # relation_type 추론 (키워드 기반)
        cypher_upper = cypher.upper()
        if "HAS_CHILD_LAW" in cypher_upper:
            got_relation_type = "child_law"
        elif "DELEGATES_TO_LAW" in cypher_upper:
            got_relation_type = "delegation"
        elif "REFERS_TO" in cypher_upper:
            got_relation_type = "reference"
        elif "HAS_ARTICLE" in cypher_upper:
            got_relation_type = "structure"

        results = neo4j_client.run_query(cypher, params)

    except Exception as exc:
        error = str(exc)

    latency_ms = (time.perf_counter() - t0) * 1000
    keyword_hit = _check_keyword_hit(results, tc.expected_result_contains)

    return RunResult(
        method="B_llm_free",
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


# ── 방식 C: ReAct Agent ────────────────────────────────────────────────────────

_TOOLS_C = [
    {
        "name": "run_cypher",
        "description": "Neo4j에 Cypher를 실행하고 결과를 반환한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "cypher": {"type": "string", "description": "실행할 Cypher 쿼리"},
                "params": {"type": "object", "description": "쿼리 파라미터"},
            },
            "required": ["cypher"],
        },
    }
]

_SYSTEM_PROMPT_C = """\
당신은 Neo4j 그래프 법령 조회 에이전트입니다.
run_cypher 도구를 사용해 법령 구조 질의에 답하세요.

Neo4j 스키마:
  Law(law_uid, law_name), Article(article_uid, article_no)
  (Law)-[:HAS_CHILD_LAW]->(Law)  — 하위법령
  (Law)-[:DELEGATES_TO_LAW]->(Law) — 위임
  (Law)-[:REFERS_TO_LAW]->(Law)  — 참조(법→법)
  (Article)-[:REFERS_TO_ARTICLE]->(Article) — 참조(조문→조문)
  (Law)-[:HAS_ARTICLE]->(Article)
"""


def run_method_c(tc: TestCase, neo4j_client: Any, api_key: str) -> RunResult:
    """방식 C: ReAct Tool-calling Agent (Gemini function calling 흉내).

    Gemini Flash-Lite는 native function calling을 지원하지 않으므로
    텍스트 기반 ReAct 루프로 구현한다.
    """
    import re
    from rag_pipeline.generation.llm_client import generate_answer

    t0 = time.perf_counter()
    error = None
    results: list[dict] = []
    input_tokens = 0
    output_tokens = 0
    got_law_name: str | None = None
    got_relation_type: str | None = None

    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    import logging as _logging
    _logger_c = _logging.getLogger(__name__)

    _TOOL_CALL_RE = re.compile(
        r"\*{0,2}[Aa]ction\*{0,2}[:\s]+run_cypher.*?\*{0,2}[Ii]nput\*{0,2}[:\s]+(\{.*?\})",
        re.DOTALL | re.IGNORECASE,
    )
    _CYPHER_JSON_RE = re.compile(r'(\{"cypher"\s*:.*?\})\s*(?:$|\n)', re.DOTALL)
    _FINAL_RE = re.compile(r"Final Answer:\s*(.+)", re.IGNORECASE | re.DOTALL)

    system_prompt = _SYSTEM_PROMPT_C + """
ReAct 형식으로 답하세요:
Thought: 생각
Action: run_cypher
Input: {"cypher": "...", "params": {"law_name": "..."}}
Observation: (도구 결과)
...
Final Answer: (최종 답변)
"""

    conversation = f"질문: {tc.query}"
    max_steps = 3

    try:
        for _step in range(max_steps):
            raw_text, usage = generate_answer(
                conversation,
                provider="gemini",
                url=url,
                model=model,
                api_key=api_key,
                timeout=20,
                max_tokens=1024,
                temperature=0.0,
                system_prompt=system_prompt,
            )
            if usage:
                input_tokens += usage.get("input", 0)
                output_tokens += usage.get("output", 0)

            _logger_c.warning("C raw_text [step=%d] query=%r | %r", _step, tc.query[:40], raw_text[:300])

            m = _TOOL_CALL_RE.search(raw_text)
            if not m:
                m = _CYPHER_JSON_RE.search(raw_text)
            if m:
                try:
                    decoder = json.JSONDecoder()
                    tool_input, _ = decoder.raw_decode(raw_text, m.start(1))
                    cypher = tool_input.get("cypher", "")
                    params = tool_input.get("params", {})
                    got_law_name = params.get("law_name")
                    # relation_type 추론
                    cu = cypher.upper()
                    if "HAS_CHILD_LAW" in cu:
                        got_relation_type = "child_law"
                    elif "DELEGATES_TO_LAW" in cu:
                        got_relation_type = "delegation"
                    elif "REFERS_TO" in cu:
                        got_relation_type = "reference"
                    elif "HAS_ARTICLE" in cu:
                        got_relation_type = "structure"

                    step_results = neo4j_client.run_query(cypher, params)
                    results = step_results
                    observation = f"결과 {len(step_results)}건: {json.dumps(step_results[:3], ensure_ascii=False)}"
                except Exception as tool_exc:
                    observation = f"오류: {tool_exc}"
                conversation += f"\n{raw_text}\nObservation: {observation}"

            if _FINAL_RE.search(raw_text):
                break

            if not m:
                break

    except Exception as exc:
        error = str(exc)

    latency_ms = (time.perf_counter() - t0) * 1000
    keyword_hit = _check_keyword_hit(results, tc.expected_result_contains)

    return RunResult(
        method="C_react_agent",
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


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _check_keyword_hit(results: list[dict], keywords: list[str]) -> bool:
    if not keywords:
        return True
    results_str = json.dumps(results, ensure_ascii=False)
    return all(kw in results_str for kw in keywords)


def _print_summary(all_results: list[RunResult]) -> None:
    methods = ["A_template", "B_llm_free", "C_react_agent"]
    print("\n" + "=" * 80)
    print("실험1 결과 요약")
    print("=" * 80)
    print(f"{'방식':<16} {'success':<10} {'law_name':<10} {'rel_type':<10} {'kw_hit':<8} {'결과수(avg)':<12} {'레이턴시(avg)':<14} {'에러수'}")
    print("-" * 80)

    for method in methods:
        method_results = [r for r in all_results if r.method == method]
        if not method_results:
            continue
        n = len(method_results)
        success_acc = sum(
            1 for r in method_results
            if r.law_name_correct and r.relation_type_correct and r.keyword_hit and not r.error
        ) / n
        law_acc = sum(1 for r in method_results if r.law_name_correct) / n
        rel_acc = sum(1 for r in method_results if r.relation_type_correct) / n
        kw_acc = sum(1 for r in method_results if r.keyword_hit) / n
        avg_count = sum(r.results_count for r in method_results) / n
        avg_latency = sum(r.latency_ms for r in method_results) / n
        errors = sum(1 for r in method_results if r.error)
        print(
            f"{method:<16} {success_acc:.0%}{'':<5} {law_acc:.0%}{'':<5} {rel_acc:.0%}{'':<5} "
            f"{kw_acc:.0%}{'':<3} {avg_count:>8.1f}    {avg_latency:>8.0f}ms    {errors}"
        )

    print("=" * 80)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    # Neo4j 클라이언트
    from rag_pipeline.graph.neo4j_client import Neo4jClient
    from rag_pipeline.graph.cypher_planner import CypherPlanner

    neo4j = Neo4jClient.from_env()
    planner = CypherPlanner.from_env()

    all_results: list[RunResult] = []

    print(f"실험1 시작: {len(TEST_CASES)}개 질의 × 3가지 방식\n")

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"[{i:02d}/{len(TEST_CASES)}] {tc.query[:50]}")

        r_a = run_method_a(tc, neo4j, planner)
        r_b = run_method_b(tc, neo4j, api_key)
        r_c = run_method_c(tc, neo4j, api_key)

        for r in (r_a, r_b, r_c):
            status = "OK" if (r.law_name_correct and r.relation_type_correct and r.keyword_hit and not r.error) else "FAIL"
            print(
                f"  {r.method:<16} [{status}] law={r.law_name_correct} rel={r.relation_type_correct} "
                f"cnt={r.results_count} {r.latency_ms:.0f}ms"
                + (f" ERR={r.error[:60]}" if r.error else "")
            )
            all_results.append(r)
        print()

    _print_summary(all_results)

    # 결과 저장
    out_dir = Path(__file__).parent.parent / "data" / "experiment_results"
    out_dir.mkdir(parents=True, exist_ok=True)

    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"experiment1_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in all_results], f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {out_path}")

    neo4j.close()


if __name__ == "__main__":
    main()
