"""LLM 호출 클라이언트.

지원 provider:
  - openai_compat: OpenAI 호환 /v1/chat/completions
  - gemini: Google Gemini API (generateContent / streamGenerateContent)
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from typing import Iterator

from ..retrieval.common import (
    LLMError,
    LLMTimeoutError,
    UpstreamHTTPError,
    UpstreamTimeoutError,
    http_json as _http_json,
)
from . import _gemini, _openai_compat

SUPPORTED_PROVIDERS = {"openai_compat", "gemini"}


def _http_json_with_timeout(method: str, url: str, payload: dict, headers: dict, timeout: int = 60):
    return _http_json(method, url, payload, headers, timeout)


def generate_answer(
    prompt: str,
    *,
    provider: str,
    url: str,
    model: str,
    api_key: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
    system_prompt: str | None = None,
    response_mime_type: str | None = None,
) -> tuple[str, dict[str, int] | None]:
    """주어진 프롬프트를 LLM에 전달하고 (답변 텍스트, token usage)를 반환한다."""
    prompt_text = prompt.strip()
    if not prompt_text:
        raise LLMError("prompt가 비어 있습니다.")

    def http_json(method, url, payload, headers):
        return _http_json(method, url, payload, headers, timeout)

    try:
        if provider == "gemini":
            return _gemini.generate(
                prompt_text=prompt_text,
                system_prompt=system_prompt,
                url=url,
                api_key=api_key,
                max_tokens=max_tokens,
                temperature=temperature,
                response_mime_type=response_mime_type,
                http_json=http_json,
            )
        return _openai_compat.generate(
            prompt_text=prompt_text,
            system_prompt=system_prompt,
            url=url,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            http_json=http_json,
        )
    except LLMError:
        raise
    except UpstreamTimeoutError as exc:
        raise LLMTimeoutError(f"LLM 요청 타임아웃: {exc}") from exc
    except UpstreamHTTPError as exc:
        raise LLMError(f"LLM HTTP 오류: {exc}") from exc


def stream_answer(
    prompt: str,
    *,
    provider: str,
    url: str,
    model: str,
    api_key: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
    system_prompt: str | None = None,
    usage_out: dict[str, int] | None = None,
) -> Iterator[str]:
    """주어진 프롬프트를 스트리밍으로 생성해 토큰(문자열 조각)을 순차 반환한다."""
    prompt_text = prompt.strip()
    if not prompt_text:
        raise LLMError("prompt가 비어 있습니다.")

    def _stream_impl() -> Iterator[str]:
        try:
            if provider == "gemini":
                yield from _gemini.stream(
                    prompt_text=prompt_text,
                    system_prompt=system_prompt,
                    url=url,
                    api_key=api_key,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    usage_out=usage_out,
                )
                return
            yield from _openai_compat.stream(
                prompt_text=prompt_text,
                system_prompt=system_prompt,
                url=url,
                api_key=api_key,
                model=model,
                timeout=timeout,
                max_tokens=max_tokens,
                temperature=temperature,
                usage_out=usage_out,
            )
        except LLMError:
            raise
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"LLM HTTP 오류: HTTP {exc.code} POST {url}\n{body}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(exc).lower():
                raise LLMTimeoutError(f"LLM 스트리밍 타임아웃: {exc}") from exc
            raise LLMError(f"LLM 네트워크 오류: POST {url}: {exc}") from exc
        except TimeoutError as exc:
            raise LLMTimeoutError(f"LLM 스트리밍 타임아웃: {exc}") from exc

    return _stream_impl()
