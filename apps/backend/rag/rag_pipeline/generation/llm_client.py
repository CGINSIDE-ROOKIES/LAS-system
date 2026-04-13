"""LLM 호출 클라이언트.

지원 provider:
  - openai_compat: OpenAI 호환 /v1/chat/completions
  - gemini: Google Gemini API (generateContent / streamGenerateContent)
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator

from ..retrieval.common import (
    LLMError,
    LLMTimeoutError,
    UpstreamHTTPError,
    UpstreamTimeoutError,
    http_json,
)

SUPPORTED_PROVIDERS = {"openai_compat", "gemini"}


# ── Gemini 유틸리티 ───────────────────────────────────────────────────────────

def _extract_text_from_gemini_response(data: dict[str, Any]) -> str:
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


def _build_gemini_payload(
    *,
    prompt_text: str,
    system_prompt: str | None,
    max_tokens: int,
    temperature: float,
    response_mime_type: str | None = None,
) -> dict[str, Any]:
    """Gemini generate/stream 공용 payload.

    response_mime_type는 비스트리밍(generateContent) 응답 제어용 선택 옵션이다.
    streamGenerateContent에서는 미사용이며, 호출부에서 None으로 두면 전송되지 않는다.
    """
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


def _extract_usage_from_openai(data: dict[str, Any]) -> dict[str, int] | None:
    """OpenAI 호환 응답에서 token usage를 추출한다. 없으면 None."""
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    return {
        "input": int(usage.get("prompt_tokens", 0)),
        "output": int(usage.get("completion_tokens", 0)),
        "total": int(usage.get("total_tokens", 0)),
    }


def _extract_usage_from_gemini(data: dict[str, Any]) -> dict[str, int] | None:
    """Gemini 응답에서 token usage를 추출한다. 없으면 None."""
    meta = data.get("usageMetadata")
    if not isinstance(meta, dict):
        return None
    return {
        "input": int(meta.get("promptTokenCount", 0)),
        "output": int(meta.get("candidatesTokenCount", 0)),
        "total": int(meta.get("totalTokenCount", 0)),
    }


def _extract_openai_response_text(data: dict[str, Any]) -> str:
    """OpenAI 호환(non-stream) 응답에서 텍스트를 추출한다."""
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


def _extract_openai_delta_text(data: dict[str, Any]) -> str:
    """OpenAI 호환(stream) chunk에서 delta 텍스트를 추출한다."""
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


def _iter_sse_json_events(resp: Any) -> Iterator[dict[str, Any]]:
    """SSE 응답 스트림에서 data: JSON 이벤트만 추출한다."""
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
        if isinstance(data, dict):
            yield data


def _build_gemini_stream_url(url: str) -> str:
    """generateContent URL을 streamGenerateContent SSE URL로 안전하게 변환한다."""
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
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query_dict = dict(query_pairs)
    query_dict["alt"] = "sse"
    query = urllib.parse.urlencode(query_dict)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, stream_path, query, parsed.fragment))


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
) -> tuple[str, dict[str, int] | None]:
    """주어진 프롬프트를 LLM에 전달하고 (답변 텍스트, token usage)를 반환한다."""
    prompt_text = prompt.strip()
    if not prompt_text:
        raise LLMError("prompt가 비어 있습니다.")

    try:
        if provider == "gemini":
            if not api_key:
                raise LLMError("GEMINI_API_KEY가 필요합니다.")
            payload = _build_gemini_payload(
                prompt_text=prompt_text,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                response_mime_type=response_mime_type,
            )
            headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
            res = http_json("POST", url, payload, headers, timeout)
            return _extract_text_from_gemini_response(res), _extract_usage_from_gemini(res)

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
        return _extract_openai_response_text(res), _extract_usage_from_openai(res)
    except LLMError:
        raise
    except UpstreamTimeoutError as exc:
        raise LLMTimeoutError(f"LLM 요청 타임아웃: {exc}") from exc
    except UpstreamHTTPError as exc:
        raise LLMError(f"LLM HTTP 오류: {exc}") from exc


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
        for data in _iter_sse_json_events(resp):
            if usage_out is not None:
                raw_usage = data.get("usage")
                if isinstance(raw_usage, dict):
                    usage_out.update(_extract_usage_from_openai(data) or {})
            delta_content = _extract_openai_delta_text(data)
            if delta_content:
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
    usage_out: dict[str, int] | None = None,
) -> Iterator[str]:
    if not api_key:
        raise LLMError("GEMINI_API_KEY가 필요합니다.")
    payload = _build_gemini_payload(
        prompt_text=prompt_text,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    call_url = _build_gemini_stream_url(url)

    req = urllib.request.Request(
        url=call_url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("x-goog-api-key", api_key)

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for data in _iter_sse_json_events(resp):
            if usage_out is not None:
                extracted = _extract_usage_from_gemini(data)
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
                yield from _stream_gemini(
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

            yield from _stream_openai_compat(
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
