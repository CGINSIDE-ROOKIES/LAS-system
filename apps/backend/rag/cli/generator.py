#!/usr/bin/env python3
"""LLM Generator 호출 유틸리티.

지원 provider:
- openai_compat: OpenAI 호환 /v1/chat/completions
- gemini: Google Gemini API (generateContent / streamGenerateContent)
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Iterator
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

from retrieval_common import RetrievalError, http_json

DEFAULT_PROVIDER = "openai_compat"
DEFAULT_MODEL = "gemini-1.5-flash"
# openai_compat provider의 기본 endpoint. 환경변수/인자로 덮어쓸 수 있다.
DEFAULT_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


def _resolve_request_options(
    *,
    provider: str | None,
    url: str | None,
    model: str | None,
    api_key: str | None,
    timeout: int | None,
    max_tokens: int | None,
    temperature: float | None,
) -> tuple[str, str, str, str, int, int, float]:
    resolved_provider = (
        (provider or "").strip()
        or os.getenv("LLM_PROVIDER", "").strip()
        or DEFAULT_PROVIDER
    )
    if resolved_provider not in {"openai_compat", "gemini"}:
        raise RetrievalError(f"지원하지 않는 provider: {resolved_provider}")

    if resolved_provider == "gemini":
        resolved_model = (
            (model or "").strip()
            or os.getenv("GEMINI_MODEL", "").strip()
            or DEFAULT_MODEL
        )
        resolved_url = (
            (url or "").strip()
            or os.getenv("GEMINI_API_URL", "").strip()
            or f"https://generativelanguage.googleapis.com/v1beta/models/{resolved_model}:generateContent"
        )
        resolved_api_key = (api_key or "").strip() or os.getenv(
            "GEMINI_API_KEY", ""
        ).strip()
    else:
        resolved_model = (model or "").strip() or os.getenv("LLM_MODEL", "").strip()
        resolved_url = (url or "").strip() or os.getenv(
            "LLM_CHAT_COMPLETIONS_URL", ""
        ).strip()
        resolved_api_key = (
            (api_key or "").strip()
            or os.getenv("LLM_API_KEY", "").strip()
            or os.getenv("OPENAI_API_KEY", "").strip()
        )
        if not resolved_url:
            raise RetrievalError(
                "openai_compat 사용 시 LLM_CHAT_COMPLETIONS_URL(또는 --url)이 필요합니다."
            )
        if not resolved_model:
            raise RetrievalError(
                "openai_compat 사용 시 LLM_MODEL(또는 --model)이 필요합니다."
            )

    resolved_timeout = (
        timeout
        if timeout is not None
        else int(os.getenv("LLM_TIMEOUT", "120").strip() or "120")
    )
    resolved_max_tokens = (
        max_tokens
        if max_tokens is not None
        else int(os.getenv("LLM_MAX_TOKENS", "256").strip() or "256")
    )
    resolved_temperature = (
        temperature
        if temperature is not None
        else float(os.getenv("LLM_TEMPERATURE", "0.2").strip() or "0.2")
    )

    return (
        resolved_provider,
        resolved_url,
        resolved_model,
        resolved_api_key,
        resolved_timeout,
        resolved_max_tokens,
        resolved_temperature,
    )


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
    *, prompt_text: str, system_prompt: str | None, max_tokens: int, temperature: float
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_prompt and system_prompt.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}
    return payload


def generate_answer(
    prompt: str,
    *,
    system_prompt: str | None = None,
    provider: str | None = None,
    url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """주어진 프롬프트를 LLM에 전달하고 답변 텍스트를 반환한다."""
    prompt_text = prompt.strip()
    if not prompt_text:
        raise RetrievalError("prompt가 비어 있습니다.")

    (
        resolved_provider,
        resolved_url,
        resolved_model,
        resolved_api_key,
        resolved_timeout,
        resolved_max_tokens,
        resolved_temperature,
    ) = _resolve_request_options(
        provider=provider,
        url=url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if resolved_provider == "gemini":
        if not resolved_api_key:
            raise RetrievalError("GEMINI_API_KEY가 필요합니다.")
        payload = _build_gemini_payload(
            prompt_text=prompt_text,
            system_prompt=system_prompt,
            max_tokens=resolved_max_tokens,
            temperature=resolved_temperature,
        )
        sep = "&" if "?" in resolved_url else "?"
        call_url = f"{resolved_url}{sep}key={urllib.parse.quote(resolved_api_key)}"
        res = http_json(
            "POST",
            call_url,
            payload,
            {"Content-Type": "application/json"},
            resolved_timeout,
        )
        return _extract_text_from_gemini_response(res)

    headers = {"Content-Type": "application/json"}
    if resolved_api_key:
        headers["Authorization"] = f"Bearer {resolved_api_key}"

    messages: list[dict[str, str]] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt_text})

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "max_tokens": resolved_max_tokens,
        "temperature": resolved_temperature,
    }

    res = http_json("POST", resolved_url, payload, headers, resolved_timeout)
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
            data_str = line[len("data:") :].strip()
            if not data_str:
                continue
            if data_str == "[DONE]":
                break
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

            content = ""
            delta = first.get("delta")
            if isinstance(delta, dict):
                delta_content = delta.get("content")
                if isinstance(delta_content, str):
                    content = delta_content
            if content:
                yield content


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
    sep = "&" if "?" in stream_url else "?"
    call_url = f"{stream_url}{sep}alt=sse&key={urllib.parse.quote(api_key)}"

    req = urllib.request.Request(
        url=call_url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:") :].strip()
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
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    yield text


def stream_answer(
    prompt: str,
    *,
    system_prompt: str | None = None,
    provider: str | None = None,
    url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
):
    """주어진 프롬프트를 스트리밍으로 생성해 토큰(문자열 조각)을 순차 반환한다."""
    prompt_text = prompt.strip()
    if not prompt_text:
        raise RetrievalError("prompt가 비어 있습니다.")

    (
        resolved_provider,
        resolved_url,
        resolved_model,
        resolved_api_key,
        resolved_timeout,
        resolved_max_tokens,
        resolved_temperature,
    ) = _resolve_request_options(
        provider=provider,
        url=url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    try:
        if resolved_provider == "gemini":
            if not resolved_api_key:
                raise RetrievalError("GEMINI_API_KEY가 필요합니다.")
            yield from _stream_gemini(
                prompt_text=prompt_text,
                system_prompt=system_prompt,
                url=resolved_url,
                api_key=resolved_api_key,
                timeout=resolved_timeout,
                max_tokens=resolved_max_tokens,
                temperature=resolved_temperature,
            )
            return

        yield from _stream_openai_compat(
            prompt_text=prompt_text,
            system_prompt=system_prompt,
            url=resolved_url,
            api_key=resolved_api_key,
            model=resolved_model,
            timeout=resolved_timeout,
            max_tokens=resolved_max_tokens,
            temperature=resolved_temperature,
        )
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RetrievalError(f"HTTP {exc.code} POST {resolved_url}\\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RetrievalError(f"Network error POST {resolved_url}: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM Generator 스크립트")
    parser.add_argument("--prompt", required=True, help="LLM으로 보낼 프롬프트")
    parser.add_argument(
        "--provider",
        default="",
        choices=["openai_compat", "gemini"],
        help="LLM provider (기본: LLM_PROVIDER 또는 openai_compat)",
    )
    parser.add_argument(
        "--url",
        default="",
        help=(
            "provider별 URL. "
            "openai_compat: LLM_CHAT_COMPLETIONS_URL 또는 --url 필수, "
            "gemini 기본: Google Generative Language API"
        ),
    )
    parser.add_argument(
        "--model",
        default="",
        help=(
            "모델명 "
            f"(openai_compat: LLM_MODEL 또는 --model 필수, gemini 기본: {DEFAULT_MODEL})"
        ),
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="인증 키 (openai: LLM_API_KEY/OPENAI_API_KEY, gemini: GEMINI_API_KEY)",
    )
    parser.add_argument("--timeout", type=int, default=120, help="요청 타임아웃(초)")
    parser.add_argument("--max-tokens", type=int, default=256, help="최대 생성 토큰")
    parser.add_argument("--temperature", type=float, default=0.2, help="생성 온도")
    parser.add_argument("--system-prompt", default="", help="시스템 프롬프트")
    parser.add_argument("--stream", action="store_true", help="스트리밍 출력 모드")
    parser.add_argument("--json", action="store_true", help="JSON 형식으로 출력")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.stream:
        chunks: list[str] = []
        try:
            for chunk in stream_answer(
                args.prompt,
                system_prompt=args.system_prompt or None,
                provider=args.provider or None,
                url=args.url or None,
                model=args.model or None,
                api_key=args.api_key or None,
                timeout=args.timeout,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
            ):
                chunks.append(chunk)
                if args.json:
                    print(
                        json.dumps(
                            {"type": "answer_delta", "delta": chunk}, ensure_ascii=False
                        ),
                        flush=True,
                    )
                else:
                    print(chunk, end="", flush=True)
        except RetrievalError as exc:
            raise SystemExit(f"[ERROR] LLM 생성 실패: {exc}") from exc

        answer = "".join(chunks).strip()
        if args.json:
            print(
                json.dumps({"type": "final", "answer": answer}, ensure_ascii=False),
                flush=True,
            )
        else:
            print()
        return 0

    try:
        answer = generate_answer(
            args.prompt,
            system_prompt=args.system_prompt or None,
            provider=args.provider or None,
            url=args.url or None,
            model=args.model or None,
            api_key=args.api_key or None,
            timeout=args.timeout,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
    except RetrievalError as exc:
        raise SystemExit(f"[ERROR] LLM 생성 실패: {exc}") from exc

    if args.json:
        print(
            json.dumps(
                {"prompt": args.prompt, "answer": answer}, ensure_ascii=False, indent=2
            )
        )
        return 0

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
