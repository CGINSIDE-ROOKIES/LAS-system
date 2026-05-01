"""OpenAI 호환 API provider 구현."""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Iterator

from ..retrieval.common import LLMError
from ._sse import iter_sse_json_events


def extract_usage(data: dict[str, Any]) -> dict[str, int] | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        "input": int(usage.get("prompt_tokens", 0)),
        "output": int(usage.get("completion_tokens", 0)),
        "total": int(usage.get("total_tokens", 0)),
    }


def extract_response_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("LLM 응답에 choices가 없습니다.")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMError("LLM 응답 choices[0] 형식이 올바르지 않습니다.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMError("LLM 응답 message 형식이 올바르지 않습니다.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMError("LLM 응답 content가 비어 있습니다.")
    return content.strip()


def extract_delta_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    if not isinstance(content, str):
        return ""
    return content


def generate(
    *,
    prompt_text: str,
    system_prompt: str | None,
    url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    temperature: float,
    http_json: Any,
) -> tuple[str, dict[str, int] | None]:
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
    res = http_json("POST", url, payload, headers)
    return extract_response_text(res), extract_usage(res)


def stream(
    *,
    prompt_text: str,
    system_prompt: str | None,
    url: str,
    api_key: str,
    model: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
    usage_out: dict[str, int] | None = None,
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
        "stream_options": {"include_usage": True},
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
        for data in iter_sse_json_events(resp):
            if usage_out is not None:
                raw_usage = data.get("usage")
                if isinstance(raw_usage, dict):
                    usage_out.update(extract_usage(data) or {})
            delta_content = extract_delta_text(data)
            if delta_content:
                yield delta_content
