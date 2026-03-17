#!/usr/bin/env python3
"""LLM Generator 호출 유틸리티.

기본 엔드포인트:
  http://sylph-wsl.ragdoll-ule.ts.net:8000/v1/chat/completions

실행 예시:
  uv run python cli/generator.py --prompt "안녕"
  uv run python cli/generator.py --prompt "안녕" --stream
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any
import urllib.error
import urllib.request

from retrieval_common import RetrievalError, http_json

DEFAULT_CHAT_COMPLETIONS_URL = (
    "http://sylph-wsl.ragdoll-ule.ts.net:8000/v1/chat/completions"
)
DEFAULT_MODEL = "jinkyeongk/Midm-2.0-Base-Instruct-AWQ"


def _resolve_request_options(
    *,
    url: str | None,
    model: str | None,
    api_key: str | None,
    timeout: int | None,
    max_tokens: int | None,
    temperature: float | None,
) -> tuple[str, str, str, int, int, float]:
    resolved_url = (
        (url or "").strip()
        or os.getenv("LLM_CHAT_COMPLETIONS_URL", "").strip()
        or DEFAULT_CHAT_COMPLETIONS_URL
    )
    resolved_model = (
        (model or "").strip() or os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL
    )
    resolved_api_key = (
        (api_key or "").strip()
        or os.getenv("LLM_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
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
        resolved_url,
        resolved_model,
        resolved_api_key,
        resolved_timeout,
        resolved_max_tokens,
        resolved_temperature,
    )


def generate_answer(
    prompt: str,
    *,
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
        resolved_url,
        resolved_model,
        resolved_api_key,
        resolved_timeout,
        resolved_max_tokens,
        resolved_temperature,
    ) = _resolve_request_options(
        url=url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    headers = {"Content-Type": "application/json"}
    if resolved_api_key:
        headers["Authorization"] = f"Bearer {resolved_api_key}"

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [{"role": "user", "content": prompt_text}],
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


def stream_answer(
    prompt: str,
    *,
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
        resolved_url,
        resolved_model,
        resolved_api_key,
        resolved_timeout,
        resolved_max_tokens,
        resolved_temperature,
    ) = _resolve_request_options(
        url=url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": [{"role": "user", "content": prompt_text}],
        "max_tokens": resolved_max_tokens,
        "temperature": resolved_temperature,
        "stream": True,
    }
    req = urllib.request.Request(
        url=resolved_url,
        method="POST",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    req.add_header("Content-Type", "application/json")
    if resolved_api_key:
        req.add_header("Authorization", f"Bearer {resolved_api_key}")

    try:
        with urllib.request.urlopen(req, timeout=resolved_timeout) as resp:
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
                if isinstance(data.get("error"), dict):
                    msg = str((data.get("error") or {}).get("message", "")).strip()
                    raise RetrievalError(msg or "LLM 스트리밍 응답에 에러가 포함되었습니다.")

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
                if not content:
                    message = first.get("message")
                    if isinstance(message, dict):
                        msg_content = message.get("content")
                        if isinstance(msg_content, str):
                            content = msg_content
                if content:
                    yield content
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RetrievalError(f"HTTP {exc.code} POST {resolved_url}\\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RetrievalError(f"Network error POST {resolved_url}: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM Generator 스크립트")
    parser.add_argument("--prompt", required=True, help="LLM으로 보낼 프롬프트")
    parser.add_argument(
        "--url",
        default="",
        help=f"chat/completions URL (기본: {DEFAULT_CHAT_COMPLETIONS_URL})",
    )
    parser.add_argument(
        "--model",
        default="",
        help=f"모델명 (기본: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="인증 키 (기본: LLM_API_KEY 또는 OPENAI_API_KEY)",
    )
    parser.add_argument("--timeout", type=int, default=120, help="요청 타임아웃(초)")
    parser.add_argument("--max-tokens", type=int, default=256, help="최대 생성 토큰")
    parser.add_argument("--temperature", type=float, default=0.2, help="생성 온도")
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
                            {"type": "answer_delta", "delta": chunk},
                            ensure_ascii=False,
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
                {
                    "prompt": args.prompt,
                    "answer": answer,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
