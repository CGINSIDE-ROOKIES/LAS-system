"""Gemini Flash-Lite 기반 Query Parser.

사용자 질문에서 법령명, 조문번호, intent를 추출하고 법률 무관 질문을 판별한다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

from ..generation.llm_client import generate_answer
from .data.few_shot import FEW_SHOT_EXAMPLES
from .data.law_names import ALIAS_MAP, LAW_NAME_LIST

logger = logging.getLogger(__name__)

DEFAULT_PARSER_MODEL_GEMINI = "gemini-2.0-flash-lite"
DEFAULT_PARSER_MODEL_OPENAI = "gpt-4o-mini"
DEFAULT_PARSER_MODEL = DEFAULT_PARSER_MODEL_GEMINI  # backward compat
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

_SYSTEM_PROMPT = """\
당신은 법률 질문 분석기입니다.
반드시 아래 형식의 JSON만 출력하세요. 설명, 코드 블록(```), 마크다운 없이 {{ 로 시작하는 순수 JSON만 출력하세요.

{{"law_names": [...], "suggested_laws": [...], "intent": "...", "is_legal": true/false, "normalized_query": "...", "hypothetical_doc": "..."}}

- law_names: [현재 질문]에 법령명이 명시된 경우만 추출. [이전 질문]에 나온 법령명은 포함하지 말 것. 추론하거나 유추하지 말 것. 없으면 []
- suggested_laws: 법령명 미명시이지만 질문 맥락에서 명확히 추론 가능한 주요 법령. 불명확하거나 law_names에 이미 있으면 []
- intent: "normative" | "case_law" | "mixed" | "graph_lookup" | null (법률 무관이면 null)
  -> "graph_lookup": 법령 구조(하위법령/위임/참조 관계) 조회 질의
- is_legal: 다음 중 하나라도 해당하면 true, 모두 해당 없으면 false
  · [현재 질문]이 법률 관련인 경우
  · [이전 질문]이 있고, [현재 질문]이 그 맥락에서 의미 있는 후속 질문인 경우
  (날씨·음식·일상 등 법률 및 이전 대화와 무관한 질문은 false)
- normalized_query: [현재 질문]만을 법률 문서 검색에 최적화된 표준 법률 용어로 변환한 검색 쿼리. [이전 질문] 내용은 포함하지 말 것.
  · 구어체·줄임말을 표준 법률 용어로 교정 (예: "월급 안주면" → "임금 미지급", "짤리면" → "해고")
  · 오타·잘못된 법령명을 교정 (예: "근로기쥰법" → "근로기준법")
  · 원문이 이미 표준 법률 용어면 그대로 반환
  · is_legal=false이면 빈 문자열 반환
- hypothetical_doc: intent가 "normative"일 때만 작성. normalized_query를 실제 조문 형식의 문장으로 변환하여 1~2문장으로 생성.
  · 질문이 벌금·과태료·처벌·제재 여부를 묻는 경우: 벌칙 조문 형태로 작성 (예: "~한 자는 X만원 이하의 벌금에 처한다.")
  · 그 외: 의무나 요건을 직접 규정하는 조문 형태로 작성 (예: "사용자는 근로자를 해고하려면 적어도 30일 전에 예고하여야 한다.")
  · 실제 법령에 근거 없이 민사 손해배상·배상 의무 조문을 임의로 만들지 말 것
  · 조문 내용에 구체적인 요건·기준·숫자·조건이 없고 "법령에서 정하는 바에 따른다" 수준의 추상적 문장이 되면 빈 문자열 "" 반환
  · intent가 "normative"가 아니면 반드시 빈 문자열 ""

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
    normalized_query: str = ""
    suggested_laws: list[str] = field(default_factory=list)
    parser_fallback: bool = False
    hypothetical_doc: str = ""


@dataclass
class QueryParserConfig:
    """QueryParser 설정."""

    api_key: str
    model: str = DEFAULT_PARSER_MODEL_GEMINI
    timeout: int = 10
    strict_mode: bool = False
    provider: str = "gemini"
    url: str = ""

    def __post_init__(self) -> None:
        if not self.url:
            if self.provider == "gemini":
                self.url = f"{_GEMINI_BASE_URL}/{self.model}:generateContent"
            else:
                self.url = _OPENAI_CHAT_URL

    @classmethod
    def from_env(cls) -> QueryParserConfig:
        """환경변수에서 설정을 읽어 QueryParserConfig를 생성한다."""
        provider = os.getenv("LLM_PROVIDER", "gemini").strip()
        if provider == "gemini":
            model = (
                os.getenv("QUERY_PARSER_MODEL", "").strip()
                or os.getenv("GEMINI_MODEL", "").strip()
                or DEFAULT_PARSER_MODEL_GEMINI
            )
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
        else:
            model = (
                os.getenv("QUERY_PARSER_MODEL", "").strip()
                or os.getenv("LLM_MODEL", "").strip()
                or DEFAULT_PARSER_MODEL_OPENAI
            )
            api_key = (
                os.getenv("LLM_API_KEY", "").strip()
                or os.getenv("OPENAI_API_KEY", "").strip()
            )
        strict = os.getenv("QUERY_PARSER_STRICT", "").strip().lower() in ("1", "true")
        timeout = int(os.getenv("QUERY_PARSER_TIMEOUT", "10").strip() or "10")
        return cls(api_key=api_key, model=model, timeout=timeout, strict_mode=strict, provider=provider)


# ── 프롬프트 빌더 ─────────────────────────────────────────────────────────────

def _build_prompt(query: str, previous_question: str | None = None) -> str:
    """few-shot 예시를 포함한 사용자 메시지를 생성한다."""
    lines: list[str] = []
    for q, expected in FEW_SHOT_EXAMPLES:
        lines.append(f"질문: {q}")
        lines.append(f"출력: {expected}")
        lines.append("")
    if previous_question:
        lines.append(f"[이전 맥락 — is_legal 판단 참고용. law_names·normalized_query 추출 금지]: {previous_question}")
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
    law_names = _normalize_law_names(data.get("law_names"))
    suggested_laws = _normalize_law_names(data.get("suggested_laws"))
    # law_names에 이미 포함된 항목은 suggested_laws에서 제거
    suggested_laws = [s for s in suggested_laws if s not in law_names]
    return QueryParseResult(
        law_names=law_names,
        intent=data.get("intent") if data.get("intent") in _VALID_INTENTS else None,
        is_legal=bool(data.get("is_legal", True)),
        normalized_query=str(data.get("normalized_query") or "").strip(),
        suggested_laws=suggested_laws,
        hypothetical_doc=str(data.get("hypothetical_doc") or "").strip(),
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

    def parse(self, query: str, previous_question: str | None = None) -> QueryParseResult:
        """질문을 파싱해 구조화 결과를 반환한다.

        strict_mode=False(기본값): 파싱 실패 시 fallback 결과 반환 + 경고 로그.
        strict_mode=True: 파싱 실패 시 예외 raise.
        """
        cfg = self._cfg
        raw_text = ""

        if not cfg.api_key:
            if cfg.strict_mode:
                raise ValueError("LLM API key가 비어 있습니다.")
            if not self._api_key_missing_warned:
                logger.warning("query_parser fallback: LLM API key 미설정으로 파서를 건너뜁니다.")
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
                _build_prompt(query, previous_question),
                provider=cfg.provider,
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
                "query_parser: query=%r law_names=%r suggested_laws=%r intent=%r is_legal=%r",
                query[:80], result.law_names, result.suggested_laws, result.intent, result.is_legal,
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
