"""NL → Cypher 템플릿 플래너.

LLM(Gemini Flash)으로 슬롯(법령명, 조문번호, 관계 타입)을 추출하고,
코드에서 안전하게 Cypher를 조립한다. 자유형 Cypher 생성은 금지.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-1.5-flash"
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

_VALID_RELATION_TYPES = frozenset({"child_law", "delegation", "reference", "structure"})

_SYSTEM_PROMPT = """\
당신은 법령 그래프 질의 분석기입니다.
반드시 아래 형식의 JSON만 출력하세요. 설명, 코드 블록(```), 마크다운 없이 {{ 로 시작하는 순수 JSON만 출력하세요.

{{"law_name": "...", "article_no": "...", "relation_type": "..."}}

- law_name: 질문에서 법령명이 명시된 경우 추출 (예: "근로기준법"). 없으면 null
- article_no: 조문번호 (예: "제17조"). 없으면 null
- relation_type: 아래 중 하나
  - "child_law"   : 하위법령(시행령/시행규칙) 목록 조회
  - "delegation"  : 위임 관계 조회 (다른 법령에 위임하는 조항)
  - "reference"   : 참조 관계 조회 (다른 법령/조문을 참조하는 관계)
  - "structure"   : 법령 조문 구조 조회 (조문 목록)
  - null          : 법령 그래프 조회가 아닌 경우
"""

_FEW_SHOT = [
    ("근로기준법의 하위법령은 무엇인가요?", '{"law_name": "근로기준법", "article_no": null, "relation_type": "child_law"}'),
    ("산업안전보건법 시행령과 시행규칙을 알려주세요.", '{"law_name": "산업안전보건법", "article_no": null, "relation_type": "child_law"}'),
    ("산업안전보건법이 위임하는 법령을 알려주세요.", '{"law_name": "산업안전보건법", "article_no": null, "relation_type": "delegation"}'),
    ("최저임금법이 시행령에 위임하는 내용을 알려주세요.", '{"law_name": "최저임금법", "article_no": null, "relation_type": "delegation"}'),
    ("근로기준법이 참조하는 다른 법령은 무엇인가요?", '{"law_name": "근로기준법", "article_no": null, "relation_type": "reference"}'),
    ("최저임금법이 다른 법령을 참조하는 경우를 알려주세요.", '{"law_name": "최저임금법", "article_no": null, "relation_type": "reference"}'),
    ("하도급거래 공정화에 관한 법률 제2조가 참조하는 조문은?", '{"law_name": "하도급거래 공정화에 관한 법률", "article_no": "제2조", "relation_type": "reference"}'),
    ("근로기준법의 조문 구조를 보여주세요.", '{"law_name": "근로기준법", "article_no": null, "relation_type": "structure"}'),
]

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# ── Cypher 템플릿 ─────────────────────────────────────────────────────────────

# T1: 하위법령 목록 (HAS_CHILD_LAW)
_CYPHER_CHILD_LAW = """
MATCH (parent:Law {law_name: $law_name})-[:HAS_CHILD_LAW]->(child:Law)
RETURN child.law_name AS child_law_name,
       child.law_uid  AS child_law_uid,
       child.classified_level AS classified_level
ORDER BY child.law_name
""".strip()

# T2: 위임 관계 (DELEGATES_TO_LAW)
_CYPHER_DELEGATION = """
MATCH (source:Law {law_name: $law_name})-[:DELEGATES_TO_LAW]->(target:Law)
RETURN target.law_name AS target_law_name,
       target.law_uid  AS target_law_uid
ORDER BY target.law_name
""".strip()

# T3: 참조 관계 — 법 → 법 (REFERS_TO_LAW)
_CYPHER_REFERENCE_LAW = """
MATCH (source:Law {law_name: $law_name})-[:REFERS_TO_LAW]->(target:Law)
RETURN 'law' AS ref_type,
       target.law_name AS ref_name,
       target.law_uid  AS ref_uid,
       null            AS ref_article_no
ORDER BY target.law_name
""".strip()

# T3b: 참조 관계 — 특정 조문 기준 (REFERS_TO_ARTICLE)
# tgt_law를 함께 traverse해 어느 법령의 조문인지 반환한다.
_CYPHER_REFERENCE_ARTICLE = """
MATCH (law:Law {law_name: $law_name})-[:HAS_ARTICLE]->(src:Article {article_no: $article_no})
MATCH (src)-[:REFERS_TO_ARTICLE]->(tgt:Article)
MATCH (tgt_law:Law)-[:HAS_ARTICLE]->(tgt)
RETURN 'article' AS ref_type,
       tgt.article_no   AS ref_article_no,
       tgt.article_uid  AS ref_uid,
       tgt_law.law_name AS ref_name
ORDER BY tgt_law.law_name,
         toInteger(split(replace(tgt.article_no, '제', ''), '조')[0]),
         tgt.article_no
""".strip()

# T4: 법령 조문 구조 (HAS_ARTICLE)
# 조문번호를 숫자 기준으로 정렬한다 (문자열 정렬 시 제10조 < 제2조 오류 방지).
_CYPHER_STRUCTURE = """
MATCH (law:Law {law_name: $law_name})-[:HAS_ARTICLE]->(article:Article)
RETURN article.article_no  AS article_no,
       article.article_uid AS article_uid
ORDER BY toInteger(split(replace(article.article_no, '제', ''), '조')[0]),
         article.article_no
""".strip()


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────

@dataclass
class GraphQuerySlots:
    """LLM이 추출한 슬롯."""

    law_name: str | None
    article_no: str | None
    relation_type: str | None  # "child_law" | "delegation" | "reference" | "structure" | None


@dataclass
class CypherPlan:
    """Cypher 조립 결과."""

    cypher: str
    params: dict[str, Any]
    relation_type: str
    slots: GraphQuerySlots


# ── 슬롯 추출 ─────────────────────────────────────────────────────────────────

def _build_prompt(query: str) -> str:
    lines: list[str] = []
    for q, expected in _FEW_SHOT:
        lines.append(f"질문: {q}")
        lines.append(f"출력: {expected}")
        lines.append("")
    lines.append(f"질문: {query}")
    lines.append("출력:")
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return json.loads(m.group(1))

    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"JSON을 찾을 수 없습니다: {text!r}")


def _parse_slots(text: str) -> GraphQuerySlots:
    data = _extract_json(text)
    relation_type = data.get("relation_type")
    if relation_type not in _VALID_RELATION_TYPES:
        relation_type = None
    return GraphQuerySlots(
        law_name=data.get("law_name") or None,
        article_no=data.get("article_no") or None,
        relation_type=relation_type,
    )


# ── CypherPlanner ─────────────────────────────────────────────────────────────

@dataclass
class CypherPlannerConfig:
    api_key: str
    model: str = _DEFAULT_MODEL
    timeout: int = 10

    @property
    def url(self) -> str:
        return f"{_GEMINI_BASE_URL}/{self.model}:generateContent"

    @classmethod
    def from_env(cls) -> "CypherPlannerConfig":
        model = (
            os.getenv("QUERY_PARSER_MODEL", "").strip()
            or os.getenv("GEMINI_MODEL", "").strip()
            or _DEFAULT_MODEL
        )
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        timeout = int(os.getenv("QUERY_PARSER_TIMEOUT", "10").strip() or "10")
        return cls(api_key=api_key, model=model, timeout=timeout)


class CypherPlanner:
    """자연어 질의를 슬롯 추출 → Cypher 조립으로 변환한다.

    보안 원칙: Cypher 문자열은 코드에서 고정 템플릿으로 조립한다.
               사용자 입력(law_name, article_no)은 반드시 params로 전달한다.
    """

    def __init__(self, config: CypherPlannerConfig) -> None:
        self._cfg = config

    @classmethod
    def from_env(cls) -> "CypherPlanner":
        return cls(CypherPlannerConfig.from_env())

    def extract_slots(self, query: str) -> GraphQuerySlots:
        """Gemini로 슬롯을 추출한다. 실패 시 빈 슬롯 반환."""
        from ..generation.llm_client import generate_answer

        if not self._cfg.api_key:
            logger.warning("cypher_planner: GEMINI_API_KEY 미설정, 슬롯 추출 건너뜀")
            return GraphQuerySlots(law_name=None, article_no=None, relation_type=None)

        raw_text = ""
        try:
            raw_text, _ = generate_answer(
                _build_prompt(query),
                provider="gemini",
                url=self._cfg.url,
                model=self._cfg.model,
                api_key=self._cfg.api_key,
                timeout=self._cfg.timeout,
                max_tokens=256,
                temperature=0.0,
                system_prompt=_SYSTEM_PROMPT,
            )
            slots = _parse_slots(raw_text)
            logger.debug(
                "cypher_planner: query=%r slots=%s", query[:80], slots
            )
            return slots
        except Exception as exc:
            logger.warning("cypher_planner 슬롯 추출 실패: %s | raw=%r", exc, raw_text or "N/A")
            return GraphQuerySlots(law_name=None, article_no=None, relation_type=None)

    def plan(self, query: str) -> CypherPlan | None:
        """슬롯 추출 → Cypher 조립. 법령명 없거나 relation_type 미결정 시 None 반환."""
        slots = self.extract_slots(query)

        if not slots.law_name:
            logger.debug("cypher_planner: law_name 없음 → None")
            return None
        if not slots.relation_type:
            logger.debug("cypher_planner: relation_type 없음 → None")
            return None

        rt = slots.relation_type

        if rt == "child_law":
            return CypherPlan(
                cypher=_CYPHER_CHILD_LAW,
                params={"law_name": slots.law_name},
                relation_type=rt,
                slots=slots,
            )

        if rt == "delegation":
            return CypherPlan(
                cypher=_CYPHER_DELEGATION,
                params={"law_name": slots.law_name},
                relation_type=rt,
                slots=slots,
            )

        if rt == "reference":
            if slots.article_no:
                return CypherPlan(
                    cypher=_CYPHER_REFERENCE_ARTICLE,
                    params={"law_name": slots.law_name, "article_no": slots.article_no},
                    relation_type=rt,
                    slots=slots,
                )
            return CypherPlan(
                cypher=_CYPHER_REFERENCE_LAW,
                params={"law_name": slots.law_name},
                relation_type=rt,
                slots=slots,
            )

        if rt == "structure":
            return CypherPlan(
                cypher=_CYPHER_STRUCTURE,
                params={"law_name": slots.law_name},
                relation_type=rt,
                slots=slots,
            )

        return None
