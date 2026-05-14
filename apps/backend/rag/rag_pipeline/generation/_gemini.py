"""Gemini API provider 구현."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Iterator

from ..retrieval.common import LLMError
from ._sse import iter_sse_json_events


def extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LLMError("Gemini 응답에 candidates가 없습니다.")
    first = candidates[0]
    if not isinstance(first, dict):
        raise LLMError("Gemini 응답 candidates[0] 형식이 올바르지 않습니다.")
    content = first.get("content")
    if not isinstance(content, dict):
        raise LLMError("Gemini 응답 content 형식이 올바르지 않습니다.")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise LLMError("Gemini 응답 parts가 없습니다.")

    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        t = part.get("text")
        if isinstance(t, str) and t:
            texts.append(t)
    out = "".join(texts).strip()
    if not out:
        raise LLMError("Gemini 응답 text가 비어 있습니다.")
    return out


def extract_usage(data: dict[str, Any]) -> dict[str, int] | None:
    meta = data.get("usageMetadata")
    if not isinstance(meta, dict):
        return None
    return {
        "input": int(meta.get("promptTokenCount", 0)),
        "output": int(meta.get("candidatesTokenCount", 0)),
        "total": int(meta.get("totalTokenCount", 0)),
    }


def build_payload(
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


def build_stream_url(url: str) -> str:
    """generateContent URL을 streamGenerateContent SSE URL로 변환한다."""
    if not url.strip():
        raise LLMError("Gemini URL이 비어 있습니다.")
    parsed = urllib.parse.urlsplit(url.strip())
    path = parsed.path
    if path.endswith(":streamGenerateContent"):
        stream_path = path
    elif path.endswith(":generateContent"):
        stream_path = path[: -len(":generateContent")] + ":streamGenerateContent"
    else:
        raise LLMError(
            "Gemini URL 형식이 올바르지 않습니다. ':generateContent' 또는 "
            "':streamGenerateContent'로 끝나야 합니다."
        )
    query_dict = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query_dict["alt"] = "sse"
    query = urllib.parse.urlencode(query_dict)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, stream_path, query, parsed.fragment))


def generate(
    *,
    prompt_text: str,
    system_prompt: str | None,
    url: str,
    api_key: str,
    max_tokens: int,
    temperature: float,
    response_mime_type: str | None,
    http_json: Any,
) -> tuple[str, dict[str, int] | None]:
    if not api_key:
        raise LLMError("LLM_API_KEY가 필요합니다.")
    payload = build_payload(
        prompt_text=prompt_text,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        response_mime_type=response_mime_type,
    )
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    res = http_json("POST", url, payload, headers)
    return extract_text(res), extract_usage(res)


def stream(
    *,
    prompt_text: str,
    system_prompt: str | None,
    url: str,
    api_key: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
    usage_out: dict[str, int] | None = None,
) -> Iterator[str]:
    if not api_key:
        raise LLMError("LLM_API_KEY가 필요합니다.")
    payload = build_payload(
        prompt_text=prompt_text,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    call_url = build_stream_url(url)

    req = urllib.request.Request(
        url=call_url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-goog-api-key", api_key)

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for data in iter_sse_json_events(resp):
            if usage_out is not None:
                extracted = extract_usage(data)
                if extracted:
                    usage_out.update(extracted)
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
