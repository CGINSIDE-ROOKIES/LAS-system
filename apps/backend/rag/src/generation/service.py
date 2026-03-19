"""LLM 생성 서비스."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator

from .llm_client import SUPPORTED_PROVIDERS, generate_answer, stream_answer
from ..retrieval.common import RetrievalError

DEFAULT_PROVIDER = "openai_compat"
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"


@dataclass
class GenerationConfig:
    """GenerationService 설정."""

    provider: str = DEFAULT_PROVIDER
    url: str = ""
    model: str = ""
    api_key: str = ""
    timeout: int = 120
    max_tokens: int = 2048
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise RetrievalError(f"지원하지 않는 provider: {self.provider}")

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
            timeout=int(os.getenv("LLM_TIMEOUT", "120").strip() or "120"),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "256").strip() or "256"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2").strip() or "0.2"),
        )


@dataclass
class GenerationResult:
    """generate() 반환값."""

    answer: str


class GenerationService:
    def __init__(self, config: GenerationConfig) -> None:
        self._cfg = config

    @classmethod
    def from_env(cls) -> GenerationService:
        """환경변수에서 설정을 읽어 인스턴스를 생성한다."""
        return cls(GenerationConfig.from_env())

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> GenerationResult:
        """프롬프트를 LLM에 전달하고 답변을 반환한다."""
        cfg = self._cfg
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
        return GenerationResult(answer=answer)

    def stream(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> Iterator[str]:
        """프롬프트를 스트리밍으로 생성해 토큰 조각을 순차 반환한다."""
        cfg = self._cfg
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
