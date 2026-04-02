"""LLM factory for parser/labeller workflows.

Profiles are environment-driven and easy to swap:
  - DOC_PROCESSOR_LLM_PROVIDER
  - DOC_PROCESSOR_LLM_MODEL
  - DOC_PROCESSOR_LLM_BASE_URL
  - DOC_PROCESSOR_LLM_API_KEY

Profile-specific overrides:
  - DOC_PROCESSOR_LLM_<PROFILE>_PROVIDER
  - DOC_PROCESSOR_LLM_<PROFILE>_MODEL
  - DOC_PROCESSOR_LLM_<PROFILE>_BASE_URL
  - DOC_PROCESSOR_LLM_<PROFILE>_API_KEY

Supported providers:
  - openai
  - openai_compat
  - gemini
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional at runtime until env is synced
    load_dotenv = None

_DOTENV_LOADED = False


def _load_local_dotenv() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True

    if load_dotenv is None:
        return

    package_root = Path(__file__).resolve().parents[1]
    package_env = package_root / ".env"
    cwd_env = Path.cwd() / ".env"

    # Keep shell-exported variables authoritative. Local .env is only a fallback.
    if package_env.exists():
        load_dotenv(package_env, override=False)
    if cwd_env.exists() and cwd_env != package_env:
        load_dotenv(cwd_env, override=False)


def _profile_env(profile: str, key: str) -> str | None:
    profile_key = f"DOC_PROCESSOR_LLM_{profile.upper()}_{key}"
    return os.getenv(profile_key) or os.getenv(f"DOC_PROCESSOR_LLM_{key}")


def get_chat_model(
    *,
    profile: str = "default",
    model_override: Any | None = None,
):
    """Return a LangChain-compatible chat model instance for parser workers."""
    if model_override is not None:
        return model_override

    _load_local_dotenv()

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
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ImportError(
                "langchain-openai is required for provider=openai/openai_compat. "
                "Install it in doc_processor."
            ) from exc

        kwargs: dict[str, Any] = {"model": model}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        return ChatOpenAI(**kwargs)

    if provider == "gemini":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:
            raise ImportError(
                "langchain-google-genai is required for provider=gemini. "
                "Install it in doc_processor."
            ) from exc

        kwargs = {"model": model}
        resolved_api_key = api_key or os.getenv("GOOGLE_API_KEY", "").strip()
        if resolved_api_key:
            kwargs["google_api_key"] = resolved_api_key
        return ChatGoogleGenerativeAI(**kwargs)

    raise ValueError(
        f"Unsupported provider '{provider}'. "
        "Supported: openai, openai_compat, gemini."
    )


__all__ = ["get_chat_model"]
