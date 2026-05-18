"""LLM 생성 서비스."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator

from ..env_config import parse_float_env, parse_int_env, read_llm_profile
from .llm_client import SUPPORTED_PROVIDERS, generate_answer, stream_answer
from ..retrieval.common import LLMError

DEFAULT_PROVIDER = "openai_compat"
# 팀 기본 운용 모델. 환경변수 LLM_MODEL로 덮어쓸 수 있다.
DEFAULT_GEMINI_MODEL = "gemini-2.5-lite"
DEFAULT_LLM_TIMEOUT = 120
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.2


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
                raise LLMError("openai_compat 사용 시 url(LLM_URL 또는 LLM_BASE_URL)이 필요합니다.")
            if not self.api_key:
                raise LLMError("openai_compat 사용 시 api_key(LLM_API_KEY)가 필요합니다.")

    @classmethod
    def from_env(cls) -> GenerationConfig:
        """환경변수에서 설정을 읽어 GenerationConfig를 생성한다."""
        profile = read_llm_profile(
            "LLM",
            default_provider=DEFAULT_PROVIDER,
            default_gemini_model=DEFAULT_GEMINI_MODEL,
            default_openai_model="",
            inherit_global=False,
        )

        try:
            timeout = parse_int_env("LLM_TIMEOUT", default=DEFAULT_LLM_TIMEOUT)
            max_tokens = parse_int_env("LLM_MAX_TOKENS", default=DEFAULT_MAX_TOKENS)
            temperature = parse_float_env("LLM_TEMPERATURE", default=DEFAULT_TEMPERATURE)
        except ValueError as exc:
            raise LLMError(f"LLM 숫자 환경변수 파싱 실패: {exc}") from exc

        return cls(
            provider=profile.provider,
            url=profile.url,
            model=profile.model,
            api_key=profile.api_key,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
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
    usage: dict[str, int] | None = None  # {"input": N, "output": N, "total": N}


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
            answer, usage = generate_answer(
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
            usage=usage,
        )

    def stream(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        usage_out: dict[str, int] | None = None,
    ) -> Iterator[str]:
        """프롬프트를 스트리밍으로 생성해 토큰 조각을 순차 반환한다.

        generate()와 동일하게 예외를 LLMError 경계로 맞춘다.
        usage_out이 주어지면 스트리밍 종료 후 token usage를 채워준다.
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
                usage_out=usage_out,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"LLM stream 실패: {type(exc).__name__}: {exc}") from exc
