"""Gemini Flash-Lite 기반 Query Parser.

사용자 질문에서 법령명, 조문번호, intent를 추출하고 법률 무관 질문을 판별한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from ..generation.llm_client import generate_answer
from .data.few_shot import FEW_SHOT_EXAMPLES
from .data.law_names import ALIAS_MAP, LAW_NAME_LIST

logger = logging.getLogger(__name__)

DEFAULT_PARSER_MODEL = "gemini-2.0-flash-lite"
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

_SYSTEM_PROMPT = """\
당신은 법률 질문 분석기입니다.
반드시 아래 형식의 JSON만 출력하세요. 설명, 코드 블록(```), 마크다운 없이 {{ 로 시작하는 순수 JSON만 출력하세요.

{{"law_names": [...], "intent": "...", "is_legal": true/false}}

- law_names: 질문에 법령명이 명시된 경우만 추출. 추론하거나 유추하지 말 것. 없으면 []
- intent: "normative" | "case_law" | "mixed" | "graph_lookup" | null (법률 무관이면 null)
  -> "graph_lookup": 법령 구조(하위법령/위임/참조 관계) 조회 질의
- is_legal: 법률 관련 질문이면 true, 아니면 false

인식 가능한 법령 목록:
{law_list}
"""

_VALID_INTENTS = frozenset({"normative", "case_law", "mixed", "graph_lookup"})
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class QueryParseResult:
    """Query Parser 반환값."""

    law_names: list[str]
    intent: str | None  # "normative" | "case_law" | "mixed" | None
    is_legal: bool
    parser_fallback: bool = False


@dataclass
class QueryParserConfig:
    """QueryParser 설정."""

    api_key: str
    model: str = DEFAULT_PARSER_MODEL
    timeout: int = 10
    strict_mode: bool = False

    @property
    def url(self) -> str:
        return f"{_GEMINI_BASE_URL}/{self.model}:generateContent"

    @classmethod
    def from_env(cls) -> QueryParserConfig:
        """환경변수에서 설정을 읽어 QueryParserConfig를 생성한다.

        모델 우선순위: QUERY_PARSER_MODEL → GEMINI_MODEL → DEFAULT_PARSER_MODEL
        """
        model = (
            os.getenv("QUERY_PARSER_MODEL", "").strip()
            or os.getenv("GEMINI_MODEL", "").strip()
            or DEFAULT_PARSER_MODEL
        )
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        strict = os.getenv("QUERY_PARSER_STRICT", "").strip().lower() in ("1", "true")
        timeout = int(os.getenv("QUERY_PARSER_TIMEOUT", "10").strip() or "10")
        return cls(api_key=api_key, model=model, timeout=timeout, strict_mode=strict)


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────────

def _build_prompt(query: str) -> str:
    """few-shot 예시를 포함한 사용자 메시지를 생성한다."""
    lines: list[str] = []
    for q, expected in FEW_SHOT_EXAMPLES:
        lines.append(f"질문: {q}")
        lines.append(f"출력: {expected}")
        lines.append("")
    lines.append(f"질문: {query}")
    lines.append("출력:")
    return "\n".join(lines)


def _build_system_prompt() -> str:
    law_list = "\n".join(f"- {name}" for name in LAW_NAME_LIST)
    return _SYSTEM_PROMPT.format(law_list=law_list)


# ── LLM 출력 파싱 ─────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """LLM 출력 텍스트에서 JSON 객체를 추출한다.

    마크다운 코드펜스(```json ... ```)로 감싸진 경우도 처리한다.
    """
    m = _JSON_BLOCK_RE.search(text)
    if m:
        return json.loads(m.group(1))

    # 코드펜스가 없으면 문자열 내 첫 JSON object를 안전하게 스캔한다.
    # 정규식 r"\{.*?\}"는 중첩 객체가 있거나 본문에 중괄호가 섞이면 오검출되기 쉬워 JSONDecoder.raw_decode로 순차 파싱한다.
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


def _normalize_law_names(raw: object) -> list[str]:
    """약칭을 정식명칭으로 변환하고, 사전에 없는 항목은 제거한다."""
    if not isinstance(raw, list):
        return []
    valid = set(LAW_NAME_LIST)
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        name = ALIAS_MAP.get(item.strip(), item.strip())
        if name in valid and name not in result:
            result.append(name)
    return result


def _parse_llm_output(text: str) -> QueryParseResult:
    data = _extract_json(text)
    return QueryParseResult(
        law_names=_normalize_law_names(data.get("law_names")),
        intent=data.get("intent") if data.get("intent") in _VALID_INTENTS else None,
        is_legal=bool(data.get("is_legal", True)),
    )


# ── QueryParser ───────────────────────────────────────────────────────────────

class QueryParser:
    """질문을 Gemini LLM으로 파싱해 구조화 결과를 반환한다."""

    def __init__(self, config: QueryParserConfig) -> None:
        self._cfg = config
        self._system_prompt = _build_system_prompt()
        # API 키가 없으면 매 요청마다 외부 호출이 실패하므로, 1회 경고 후 즉시 fallback한다.
        self._api_key_missing_warned = False

    @classmethod
    def from_env(cls) -> QueryParser:
        """환경변수에서 설정을 읽어 인스턴스를 생성한다."""
        return cls(QueryParserConfig.from_env())

    def parse(self, query: str) -> QueryParseResult:
        """질문을 파싱해 구조화 결과를 반환한다.

        strict_mode=False(기본값): 파싱 실패 시 fallback 결과 반환 + 경고 로그.
        strict_mode=True: 파싱 실패 시 예외 raise.
        """
        cfg = self._cfg
        raw_text = ""

        if not cfg.api_key:
            if cfg.strict_mode:
                raise ValueError("GEMINI_API_KEY가 비어 있습니다.")
            if not self._api_key_missing_warned:
                logger.warning("query_parser fallback: GEMINI_API_KEY 미설정으로 파서를 건너뜁니다.")
                self._api_key_missing_warned = True
            return QueryParseResult(
                law_names=[],
                intent=None,
                is_legal=True,
                parser_fallback=True,
            )

        try:
            # QueryParser는 현재 동기 LLM 클라이언트(generate_answer)를 사용한다.
            # API 라우터도 sync endpoint로 동작해 일관성을 유지한다.
            raw_text, _ = generate_answer(
                _build_prompt(query),
                provider="gemini",
                url=cfg.url,
                model=cfg.model,
                api_key=cfg.api_key,
                timeout=cfg.timeout,
                max_tokens=1024,
                temperature=0.0,
                system_prompt=self._system_prompt,
            )
            result = _parse_llm_output(raw_text)
            logger.debug(
                "query_parser: query=%r law_names=%r intent=%r is_legal=%r",
                query[:80], result.law_names, result.intent, result.is_legal,
            )
            return result

        except Exception as exc:
            if cfg.strict_mode:
                raise
            logger.warning(
                "query_parser fallback: parser_fallback=true query=%r error=%s raw_text=%r",
                query[:80], exc, raw_text[:240],
            )
            return QueryParseResult(
                law_names=[],
                intent=None,
                is_legal=True,
                parser_fallback=True,
            )
