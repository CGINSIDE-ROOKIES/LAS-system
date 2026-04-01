"""LLM 호출 클라이언트.

지원 provider:
  - openai_compat: OpenAI 호환 /v1/chat/completions
  - gemini: Google Gemini API (generateContent / streamGenerateContent)
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterator

from ..retrieval.common import RetrievalError, http_json

SUPPORTED_PROVIDERS = {"openai_compat", "gemini"}


# ── Gemini 유틸리티 ───────────────────────────────────────────────────────────

def _extract_text_from_gemini_response(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RetrievalError("Gemini 응답에 candidates가 없습니다.")
    first = candidates[0]
    if not isinstance(first, dict):
        raise RetrievalError("Gemini 응답 candidates[0] 형식이 올바르지 않습니다.")
    content = first.get("content")
    if not isinstance(content, dict):
        raise RetrievalError("Gemini 응답 content 형식이 올바르지 않습니다.")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise RetrievalError("Gemini 응답 parts가 없습니다.")

    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        t = part.get("text")
        if isinstance(t, str) and t:
            texts.append(t)
    out = "".join(texts).strip()
    if not out:
        raise RetrievalError("Gemini 응답 text가 비어 있습니다.")
    return out


def _build_gemini_payload(
    *,
    prompt_text: str,
    system_prompt: str | None,
    max_tokens: int,
    temperature: float,
    response_mime_type: str | None = None,
) -> dict[str, Any]:
    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "maxOutputTokens": max_tokens,
    }
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": generation_config,
    }
    if system_prompt and system_prompt.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}
    return payload


# ── 단일 응답 ─────────────────────────────────────────────────────────────────

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
) -> str:
    """주어진 프롬프트를 LLM에 전달하고 답변 텍스트를 반환한다."""
    prompt_text = prompt.strip()
    if not prompt_text:
        raise RetrievalError("prompt가 비어 있습니다.")

    if provider == "gemini":
        if not api_key:
            raise RetrievalError("GEMINI_API_KEY가 필요합니다.")
        payload = _build_gemini_payload(
            prompt_text=prompt_text,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            response_mime_type=response_mime_type,
        )
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        res = http_json("POST", url, payload, headers, timeout)
        return _extract_text_from_gemini_response(res)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    messages: list[dict[str, str]] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt_text})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    res = http_json("POST", url, payload, headers, timeout)
    choices = res.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RetrievalError("LLM 응답에 choices가 없습니다.")
    first = choices[0]
    if not isinstance(first, dict):
        raise RetrievalError("LLM 응답 choices[0] 형식이 올바르지 않습니다.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RetrievalError("LLM 응답 message 형식이 올바르지 않습니다.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RetrievalError("LLM 응답 content가 비어 있습니다.")
    return content.strip()


# ── 스트리밍 ──────────────────────────────────────────────────────────────────

def _stream_openai_compat(
    *,
    prompt_text: str,
    system_prompt: str | None,
    url: str,
    api_key: str,
    model: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
) -> Iterator[str]:
    messages: list[dict[str, str]] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt_text})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    req = urllib.request.Request(
        url=url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                data = json.loads(data_str)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            first = choices[0]
            if not isinstance(first, dict):
                continue
            delta = first.get("delta")
            if isinstance(delta, dict):
                delta_content = delta.get("content")
                if isinstance(delta_content, str) and delta_content:
                    yield delta_content


def _stream_gemini(
    *,
    prompt_text: str,
    system_prompt: str | None,
    url: str,
    api_key: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
) -> Iterator[str]:
    payload = _build_gemini_payload(
        prompt_text=prompt_text,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    stream_url = url.replace(":generateContent", ":streamGenerateContent")
    call_url = f"{stream_url}?alt=sse"

    req = urllib.request.Request(
        url=call_url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-goog-api-key", api_key)

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str:
                continue
            try:
                data = json.loads(data_str)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            candidates = data.get("candidates")
            if not isinstance(candidates, list) or not candidates:
                continue
            first = candidates[0]
            if not isinstance(first, dict):
                continue
            content = first.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        yield text


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
) -> Iterator[str]:
    """주어진 프롬프트를 스트리밍으로 생성해 토큰(문자열 조각)을 순차 반환한다."""
    prompt_text = prompt.strip()
    if not prompt_text:
        raise RetrievalError("prompt가 비어 있습니다.")

    try:
        if provider == "gemini":
            if not api_key:
                raise RetrievalError("GEMINI_API_KEY가 필요합니다.")
            yield from _stream_gemini(
                prompt_text=prompt_text,
                system_prompt=system_prompt,
                url=url,
                api_key=api_key,
                timeout=timeout,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return

        yield from _stream_openai_compat(
            prompt_text=prompt_text,
            system_prompt=system_prompt,
            url=url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RetrievalError(f"HTTP {exc.code} POST {url}\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RetrievalError(f"Network error POST {url}: {exc}") from exc
