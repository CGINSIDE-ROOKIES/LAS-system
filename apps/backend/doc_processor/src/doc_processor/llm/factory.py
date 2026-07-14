"""LLM factory for parser/labeller workflows."""

from __future__ import annotations

import os
from typing import Any

from ..env import ensure_local_env_loaded


def _profile_env(profile: str, key: str) -> str | None:
    profile_key = f"DOC_PROCESSOR_LLM_{profile.upper()}_{key}"
    value = os.getenv(profile_key) or os.getenv(f"DOC_PROCESSOR_LLM_{key}")
    if value:
        return value
    return None


def _profile_float_env(profile: str, key: str) -> float | None:
    raw = _profile_env(profile, key)
    if raw is None or not raw.strip():
        return None
    return float(raw)


def _openai_base_url(profile: str) -> str:
    base_url = (_profile_env(profile, "BASE_URL") or "").strip()
    if base_url:
        return base_url

    url = (
        _profile_env(profile, "URL")
        or ""
    ).strip()
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")]
    return url


def get_chat_model(
    *,
    profile: str = "default",
    model_override: Any | None = None,
    timeout_seconds: float | None = None,
):
    if model_override is not None:
        return model_override

    ensure_local_env_loaded()

    provider = (_profile_env(profile, "PROVIDER") or "openai_compat").strip().lower()
    model = (_profile_env(profile, "MODEL") or "").strip()
    base_url = _openai_base_url(profile)
    api_key = (_profile_env(profile, "API_KEY") or "").strip()
    resolved_timeout_seconds = timeout_seconds
    if resolved_timeout_seconds is None:
        resolved_timeout_seconds = _profile_float_env(profile, "TIMEOUT_SECONDS")

    if not model:
        raise ValueError(
            "Missing model name. Set DOC_PROCESSOR_LLM_MODEL or "
            f"DOC_PROCESSOR_LLM_{profile.upper()}_MODEL."
        )

    if provider in {"openai", "openai_compat"}:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {"model": model}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        if resolved_timeout_seconds is not None:
            kwargs["timeout"] = resolved_timeout_seconds
        return ChatOpenAI(**kwargs)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs = {"model": model}
        if api_key:
            kwargs["google_api_key"] = api_key
        if resolved_timeout_seconds is not None:
            kwargs["timeout"] = resolved_timeout_seconds
        return ChatGoogleGenerativeAI(**kwargs)

    raise ValueError(
        f"Unsupported provider '{provider}'. Supported: openai, openai_compat, gemini."
    )


def get_structured_method(*, profile: str = "default") -> str | None:
    ensure_local_env_loaded()
    val = (_profile_env(profile, "STRUCTURED_METHOD") or "").strip().lower()
    if val in {"json_mode", "json_schema"}:
        return val
    return None


__all__ = ["get_chat_model", "get_structured_method"]
