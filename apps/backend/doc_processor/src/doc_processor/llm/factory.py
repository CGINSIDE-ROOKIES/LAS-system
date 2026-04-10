"""LLM factory for parser/labeller workflows."""

from __future__ import annotations

import os
from typing import Any

from ..env import ensure_local_env_loaded


def _profile_env(profile: str, key: str) -> str | None:
    profile_key = f"DOC_PROCESSOR_LLM_{profile.upper()}_{key}"
    return os.getenv(profile_key) or os.getenv(f"DOC_PROCESSOR_LLM_{key}")


def get_chat_model(*, profile: str = "default", model_override: Any | None = None):
    if model_override is not None:
        return model_override

    ensure_local_env_loaded()

    provider = (_profile_env(profile, "PROVIDER") or "openai_compat").strip().lower()
    model = (_profile_env(profile, "MODEL") or "").strip()
    base_url = (_profile_env(profile, "BASE_URL") or "").strip()
    api_key = (_profile_env(profile, "API_KEY") or "").strip()

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
        return ChatOpenAI(**kwargs)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs = {"model": model}
        resolved_api_key = api_key or os.getenv("GOOGLE_API_KEY", "").strip()
        if resolved_api_key:
            kwargs["google_api_key"] = resolved_api_key
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
