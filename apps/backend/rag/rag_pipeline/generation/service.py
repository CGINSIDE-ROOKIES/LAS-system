"""LLM 생성 서비스."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Iterator

from .llm_client import SUPPORTED_PROVIDERS, generate_answer, stream_answer
from ..retrieval.common import LLMError

DEFAULT_PROVIDER = "openai_compat"
# 팀 기본 운용 모델. 환경변수 GEMINI_MODEL로 언제든 덮어쓸 수 있다.
DEFAULT_GEMINI_MODEL = "gemini-2.5-lite"
DEFAULT_LLM_TIMEOUT = 120
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.2


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise LLMError(f"{name}는 정수여야 합니다. 현재 값: {raw!r}") from exc


def _parse_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise LLMError(f"{name}는 숫자(float)여야 합니다. 현재 값: {raw!r}") from exc


@dataclass
class GenerationConfig:
    """GenerationService 설정."""

    provider: str = DEFAULT_PROVIDER
    url: str = ""
    model: str = ""
    api_key: str = ""
    timeout: int = DEFAULT_LLM_TIMEOUT
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise LLMError(f"지원하지 않는 provider: {self.provider}")
        if self.provider == "openai_compat":
            if not self.model:
                raise LLMError("openai_compat 사용 시 model(LLM_MODEL)이 필요합니다.")
            if not self.url:
                raise LLMError("openai_compat 사용 시 url(LLM_CHAT_COMPLETIONS_URL)이 필요합니다.")
            if not self.api_key:
                raise LLMError("openai_compat 사용 시 api_key(LLM_API_KEY 또는 OPENAI_API_KEY)가 필요합니다.")

    @classmethod
    def from_env(cls) -> GenerationConfig:
        """환경변수에서 설정을 읽어 GenerationConfig를 생성한다."""
        provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip()

        if provider == "gemini":
            model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
            url = (
                os.getenv("GEMINI_API_URL", "").strip()
                or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            )
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
        else:
            model = os.environ["LLM_MODEL"].strip()
            url = os.environ["LLM_CHAT_COMPLETIONS_URL"].strip()
            api_key = (
                os.getenv("LLM_API_KEY", "").strip()
                or os.getenv("OPENAI_API_KEY", "").strip()
            )

        return cls(
            provider=provider,
            url=url,
            model=model,
            api_key=api_key,
            timeout=_parse_int_env("LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT),
            max_tokens=_parse_int_env("LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS),
            temperature=_parse_float_env("LLM_TEMPERATURE", DEFAULT_TEMPERATURE),
        )


@dataclass
class GenerationResult:
    """generate() 반환값.

    answer 외 필드는 향후 사용량/추적 메타데이터 확장을 위한 슬롯이다.
    """

    answer: str
    provider: str = ""
    model: str = ""
    latency_ms: int | None = None


class GenerationService:
    def __init__(self, config: GenerationConfig) -> None:
        self._cfg = config

    @classmethod
    def from_env(cls) -> GenerationService:
        """환경변수에서 설정을 읽어 인스턴스를 생성하는 편의 메서드."""
        return cls(GenerationConfig.from_env())

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> GenerationResult:
        """프롬프트를 LLM에 전달하고 답변을 반환한다."""
        cfg = self._cfg
        t0 = time.perf_counter()
        try:
            answer = generate_answer(
                prompt,
                provider=cfg.provider,
                url=cfg.url,
                model=cfg.model,
                api_key=cfg.api_key,
                timeout=cfg.timeout,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                system_prompt=system_prompt,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"LLM generate 실패: {type(exc).__name__}: {exc}") from exc
        return GenerationResult(
            answer=answer,
            provider=cfg.provider,
            model=cfg.model,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    def stream(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> Iterator[str]:
        """프롬프트를 스트리밍으로 생성해 토큰 조각을 순차 반환한다.

        generate()와 동일하게 예외를 LLMError 경계로 맞춘다.
        """
        cfg = self._cfg
        try:
            yield from stream_answer(
                prompt,
                provider=cfg.provider,
                url=cfg.url,
                model=cfg.model,
                api_key=cfg.api_key,
                timeout=cfg.timeout,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                system_prompt=system_prompt,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"LLM stream 실패: {type(exc).__name__}: {exc}") from exc
