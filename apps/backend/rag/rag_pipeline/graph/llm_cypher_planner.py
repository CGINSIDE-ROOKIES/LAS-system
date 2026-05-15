"""NL2Cypher 방식 B — LLM 자유 Cypher 생성.

CypherGuard로 injection 방어 후 Neo4j에 실행한다.
기존 CypherPlanner(방식 A)와 동일한 CypherPlan 인터페이스를 구현하므로
graph.py 라우터 변경 없이 GRAPH_QUERY_MODE env 스위칭이 가능하다.

GRAPH_QUERY_MODE:
  "template"                        → CypherPlanner (방식 A, 기본)
  "llm_free"                        → LlmCypherPlanner (방식 B)
  "llm_free_with_template_fallback" → LlmCypherPlannerWithFallback (B → A)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from ..env_config import parse_float_env, parse_int_env, read_llm_profile
from .cypher_planner import (
    CypherPlan,
    CypherPlanner,
    GraphQuerySlots,
    _extract_json,
    _resolve_law_name_alias,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-1.5-flash"

# ── CypherGuard ───────────────────────────────────────────────────────────────

_FORBIDDEN_KEYWORDS = frozenset({
    "CREATE", "MERGE", "SET", "DELETE", "DETACH",
    "DROP", "CALL", "LOAD", "APOC", "REMOVE",  # REMOVE 추가 (P1)
})
_FORBIDDEN_PATTERNS = [re.compile(r"\bUNION\b", re.IGNORECASE)]
_ALLOWED_RELS = frozenset({
    "HAS_ARTICLE", "HAS_CHILD_LAW", "DELEGATES_TO_LAW",
    "REFERS_TO_LAW", "REFERS_TO_ARTICLE",
})
# `[:TYPE]` 및 `[r:TYPE]`, `[r:TYPE*]` 등 변수·범위 포함 패턴 모두 캡처 (P1)
_REL_RE = re.compile(r"\[(?:\w+\s*:\s*|:)(\w+)")
# 가변 길이 관계 패턴 전체 캡처: 타입 있음/없음, 변수 있음/없음 통합
# 예) [*], [r*], [:TYPE*], [r:TYPE*1..3] → * 이후 범위 문자열을 group(1)으로 캡처
_VAR_LEN_RE = re.compile(r"\[\w*(?::\w+)?\*([^\]]*)]")


class CypherGuardError(ValueError):
    pass


class CypherGuard:
    """실행 전 Cypher 안전성 검증 (injection/allowlist)."""

    _MAX_VAR_LEN_DEPTH = 5

    @staticmethod
    def validate(cypher: str) -> None:
        upper = cypher.upper()
        for kw in _FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{kw}\b", upper):
                raise CypherGuardError(f"forbidden keyword: {kw}")
        for pat in _FORBIDDEN_PATTERNS:
            if pat.search(cypher):
                raise CypherGuardError("UNION is not allowed")
        for rel in _REL_RE.findall(cypher):
            if rel.upper() not in _ALLOWED_RELS:
                raise CypherGuardError(f"forbidden relationship type: {rel}")
        if "MATCH" not in upper:
            raise CypherGuardError("query must contain at least one MATCH clause")
        # 상한 없는 가변 길이 경로 차단 (순환 그래프에서 무한 탐색 방지)
        CypherGuard._validate_var_length(cypher)

    @staticmethod
    def _validate_var_length(cypher: str) -> None:
        # 타입 있음/없음, 변수 있음/없음 모든 가변 길이 패턴 통합 검사
        for m in _VAR_LEN_RE.finditer(cypher):
            spec = m.group(1)  # * 이후 문자열: "", "3", "1..3", "1..", "..3"
            if ".." in spec:
                upper_str = spec.split("..")[-1]
                if not upper_str:
                    raise CypherGuardError(
                        "unbounded variable-length path (*N..) is not allowed; "
                        f"use *1..{CypherGuard._MAX_VAR_LEN_DEPTH}"
                    )
                if int(upper_str) > CypherGuard._MAX_VAR_LEN_DEPTH:
                    raise CypherGuardError(
                        f"variable-length path depth {upper_str} exceeds max "
                        f"{CypherGuard._MAX_VAR_LEN_DEPTH}"
                    )
            else:
                # "" (*단독) 또는 "3" (*N 단독) → 상한 없음
                raise CypherGuardError(
                    f"unbounded variable-length path '*{spec}' is not allowed; "
                    f"use *1..{CypherGuard._MAX_VAR_LEN_DEPTH}"
                )


# ── 시스템 프롬프트 ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
당신은 Neo4j Cypher 전문가입니다.
아래 스키마에서 자연어 질의에 맞는 Cypher를 생성하세요.

스키마:
  노드: Law(law_uid, law_name, classified_level), Article(article_uid, article_no_display)
  관계:
    (Law)-[:HAS_ARTICLE]->(Article)
    (Law)-[:HAS_CHILD_LAW]->(Law)
    (Law)-[:DELEGATES_TO_LAW]->(Law)
    (Law)-[:REFERS_TO_LAW]->(Law)
    (Article)-[:REFERS_TO_ARTICLE {target_paragraph_nos}]->(Article)

중요: Article 노드의 조문번호 필드는 반드시 article_no_display 를 사용 (article_no 는 존재하지 않음)

규칙:
  - MATCH/OPTIONAL MATCH/WHERE/RETURN/ORDER BY/LIMIT/WITH만 허용
  - CREATE/MERGE/SET/DELETE/DETACH/DROP/CALL/LOAD/UNION/apoc.* 절대 금지
  - 파라미터는 반드시 $law_name, $article_no 형식 사용 (값 직접 삽입 금지)
  - 가변 길이 경로 사용 시 반드시 상한 명시: *1..5 형식 (예: [:REFERS_TO_ARTICLE*1..3])
    상한 없는 * 또는 *N.. 는 절대 금지 (그래프 순환으로 무한 탐색 발생)
  - 반드시 아래 JSON 형식만 출력 (설명/코드블록/마크다운 금지):
    {"cypher": "...", "params": {"law_name": "..."}}

relation_type별 필수 RETURN alias:
  child_law:  child_law_name, child_law_uid, classified_level
  delegation: target_law_name, target_law_uid, classified_level
  reference(법→법): ref_type(='law'), ref_name, ref_uid, ref_article_no(=null), ref_classified_level
  reference(조문):  ref_type(='article'), ref_article_no, ref_uid, ref_name, src_article_no, ref_paragraph_nos
  structure:  article_no, article_uid
"""

_FEW_SHOT = [
    (
        "근로기준법의 하위법령은 무엇인가요?",
        '{"cypher": "MATCH (parent:Law {law_name: $law_name})-[:HAS_CHILD_LAW]->(child:Law) RETURN child.law_name AS child_law_name, child.law_uid AS child_law_uid, child.classified_level AS classified_level ORDER BY child.law_name", "params": {"law_name": "근로기준법"}}',
    ),
    (
        "산업안전보건법 시행령과 시행규칙을 알려주세요.",
        '{"cypher": "MATCH (parent:Law {law_name: $law_name})-[:HAS_CHILD_LAW]->(child:Law) RETURN child.law_name AS child_law_name, child.law_uid AS child_law_uid, child.classified_level AS classified_level ORDER BY child.law_name", "params": {"law_name": "산업안전보건법"}}',
    ),
    (
        "산업안전보건법이 위임하는 법령을 알려주세요.",
        '{"cypher": "MATCH (source:Law {law_name: $law_name})-[:DELEGATES_TO_LAW]->(target:Law) RETURN target.law_name AS target_law_name, target.law_uid AS target_law_uid, target.classified_level AS classified_level ORDER BY target.law_name", "params": {"law_name": "산업안전보건법"}}',
    ),
    (
        "최저임금법이 시행령에 위임하는 내용을 알려주세요.",
        '{"cypher": "MATCH (source:Law {law_name: $law_name})-[:DELEGATES_TO_LAW]->(target:Law) RETURN target.law_name AS target_law_name, target.law_uid AS target_law_uid, target.classified_level AS classified_level ORDER BY target.law_name", "params": {"law_name": "최저임금법"}}',
    ),
    (
        "근로기준법이 참조하는 다른 법령은 무엇인가요?",
        r"""{"cypher": "MATCH (source:Law {law_name: $law_name})-[:REFERS_TO_LAW]->(target:Law) RETURN 'law' AS ref_type, target.law_name AS ref_name, target.law_uid AS ref_uid, null AS ref_article_no, target.classified_level AS ref_classified_level ORDER BY target.law_name", "params": {"law_name": "근로기준법"}}""",
    ),
    (
        "최저임금법이 다른 법령을 참조하는 경우를 알려주세요.",
        r"""{"cypher": "MATCH (source:Law {law_name: $law_name})-[:REFERS_TO_LAW]->(target:Law) RETURN 'law' AS ref_type, target.law_name AS ref_name, target.law_uid AS ref_uid, null AS ref_article_no, target.classified_level AS ref_classified_level ORDER BY target.law_name", "params": {"law_name": "최저임금법"}}""",
    ),
    (
        "하도급거래 공정화에 관한 법률 제2조가 참조하는 조문은?",
        r"""{"cypher": "MATCH (law:Law {law_name: $law_name})-[:HAS_ARTICLE]->(src:Article {article_no_display: $article_no}) MATCH (src)-[r:REFERS_TO_ARTICLE]->(tgt:Article) MATCH (tgt_law:Law)-[:HAS_ARTICLE]->(tgt) RETURN 'article' AS ref_type, tgt.article_no_display AS ref_article_no, tgt.article_uid AS ref_uid, tgt_law.law_name AS ref_name, src.article_no_display AS src_article_no, r.target_paragraph_nos AS ref_paragraph_nos ORDER BY tgt_law.law_name, toInteger(split(replace(tgt.article_no_display, '제', ''), '조')[0]), tgt.article_no_display", "params": {"law_name": "하도급거래 공정화에 관한 법률", "article_no": "제2조"}}""",
    ),
    (
        "근로기준법의 조문 구조를 보여주세요.",
        r"""{"cypher": "MATCH (law:Law {law_name: $law_name})-[:HAS_ARTICLE]->(article:Article) RETURN article.article_no_display AS article_no, article.article_uid AS article_uid ORDER BY toInteger(split(replace(article.article_no_display, '제', ''), '조')[0]), article.article_no_display", "params": {"law_name": "근로기준법"}}""",
    ),
]


def _build_prompt(query: str) -> str:
    lines: list[str] = []
    for q, expected in _FEW_SHOT:
        lines.append(f"질문: {q}")
        lines.append(f"출력: {expected}")
        lines.append("")
    lines.append(f"질문: {query}")
    lines.append("출력:")
    return "\n".join(lines)


def _infer_relation_type(cypher: str) -> str | None:
    upper = cypher.upper()
    if "HAS_CHILD_LAW" in upper:
        return "child_law"
    if "DELEGATES_TO_LAW" in upper:
        return "delegation"
    if "REFERS_TO" in upper:
        return "reference"
    if "HAS_ARTICLE" in upper:
        return "structure"
    return None


# ── LlmCypherPlannerConfig ────────────────────────────────────────────────────

@dataclass
class LlmCypherPlannerConfig:
    api_key: str
    model: str = _DEFAULT_MODEL
    provider: str = "gemini"
    url: str = ""
    timeout: int = 15
    max_tokens: int = 2048
    temperature: float = 0.0

    @classmethod
    def from_env(cls) -> "LlmCypherPlannerConfig":
        profile = read_llm_profile(
            "GRAPH_LLM",
            default_provider="gemini",
            default_gemini_model=_DEFAULT_MODEL,
            default_openai_model="",
            inherited_provider_vars=("QUERY_PARSER_LLM_PROVIDER",),
            inherited_model_vars=("QUERY_PARSER_LLM_MODEL",),
            inherited_url_vars=("QUERY_PARSER_LLM_URL",),
            inherited_api_key_vars=("QUERY_PARSER_LLM_API_KEY",),
        )
        timeout = parse_int_env(
            "GRAPH_LLM_TIMEOUT",
            "QUERY_PARSER_LLM_TIMEOUT",
            default=15,
        )
        max_tokens = parse_int_env("GRAPH_LLM_MAX_TOKENS", default=2048)
        temperature = parse_float_env("GRAPH_LLM_TEMPERATURE", default=0.0)
        return cls(
            api_key=profile.api_key,
            model=profile.model,
            provider=profile.provider,
            url=profile.url,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
        )


# ── LlmCypherPlanner ─────────────────────────────────────────────────────────

class LlmCypherPlanner:
    """LLM이 Cypher를 직접 생성하는 방식 B.

    인터페이스는 CypherPlanner와 동일(plan() → CypherPlan | None)하므로
    graph.py 라우터 변경 없이 GRAPH_QUERY_MODE env로 전환 가능하다.
    """

    def __init__(self, config: LlmCypherPlannerConfig) -> None:
        self._cfg = config

    @classmethod
    def from_env(cls) -> "LlmCypherPlanner":
        return cls(LlmCypherPlannerConfig.from_env())

    def plan(self, query: str) -> CypherPlan | None:
        from ..generation.llm_client import generate_answer

        if not self._cfg.api_key:
            logger.warning("llm_cypher_planner: LLM API key 미설정, 건너뜀")
            return None
        if not self._cfg.url:
            logger.warning("llm_cypher_planner: LLM URL 미설정, 건너뜀")
            return None

        # LLM 호출 전 사전 필터 — 쿼리에 금지 키워드가 직접 포함된 경우 즉시 차단
        query_upper = query.upper()
        for kw in _FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{kw}\b", query_upper):
                logger.warning("llm_cypher_planner: pre-filter 차단 (keyword=%s)", kw)
                return None

        raw_text = ""
        try:
            raw_text, _ = generate_answer(
                _build_prompt(query),
                provider=self._cfg.provider,
                url=self._cfg.url,
                model=self._cfg.model,
                api_key=self._cfg.api_key,
                timeout=self._cfg.timeout,
                max_tokens=self._cfg.max_tokens,
                temperature=self._cfg.temperature,
                system_prompt=_SYSTEM_PROMPT,
                response_mime_type="application/json",
            )

            data = _extract_json(raw_text)
            cypher: str = data.get("cypher", "").strip()
            params: dict[str, Any] = data.get("params", {})

            if not cypher:
                logger.warning("llm_cypher_planner: 빈 Cypher — raw=%r", raw_text[:200])
                return None

            CypherGuard.validate(cypher)

            relation_type = _infer_relation_type(cypher)
            if not relation_type:
                logger.warning("llm_cypher_planner: relation_type 추론 실패 — cypher=%r", cypher[:120])
                return None

            raw_law_name = params.get("law_name") or None
            resolved_law_name = _resolve_law_name_alias(raw_law_name)
            if resolved_law_name != raw_law_name:
                params["law_name"] = resolved_law_name
                logger.debug("llm_cypher_planner: alias 해결 %r → %r", raw_law_name, resolved_law_name)

            slots = GraphQuerySlots(
                law_name=resolved_law_name,
                article_no=params.get("article_no") or None,
                relation_type=relation_type,
            )
            logger.debug("llm_cypher_planner: query=%r slots=%s", query[:80], slots)
            return CypherPlan(cypher=cypher, params=params, relation_type=relation_type, slots=slots)

        except CypherGuardError as exc:
            logger.warning("llm_cypher_planner: CypherGuard 차단: %s", exc)
            return None
        except Exception as exc:
            logger.warning("llm_cypher_planner: 실패: %s | raw=%r", exc, raw_text[:200] or "N/A")
            return None


# ── LlmCypherPlannerWithFallback ──────────────────────────────────────────────

class LlmCypherPlannerWithFallback:
    """방식 B 시도 후 None이면 방식 A(CypherPlanner)로 fallback."""

    def __init__(self, llm: LlmCypherPlanner, template: CypherPlanner) -> None:
        self._llm = llm
        self._template = template

    @classmethod
    def from_env(cls) -> "LlmCypherPlannerWithFallback":
        return cls(
            llm=LlmCypherPlanner.from_env(),
            template=CypherPlanner.from_env(),
        )

    def plan(self, query: str) -> CypherPlan | None:
        result = self._llm.plan(query)
        if result is not None:
            return result
        logger.debug("llm_cypher_planner: B 실패 → CypherPlanner(A) fallback")
        return self._template.plan(query)
