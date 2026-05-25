"""Environment-driven model configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"

OPENAI_COMPAT_PROVIDERS = {"openai", "openai_compat"}
_BACKEND_ENV_LOADED = False


@dataclass(frozen=True)
class LLMProfile:
    provider: str
    model: str
    url: str
    api_key: str


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_backend_env(*, override: bool = False) -> None:
    """Load the consolidated backend env file for local runs."""

    global _BACKEND_ENV_LOADED
    if _BACKEND_ENV_LOADED:
        return
    _BACKEND_ENV_LOADED = True

    env_path = backend_root() / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        _load_simple_env_file(env_path, override=override)
        return

    load_dotenv(env_path, override=override)


def _load_simple_env_file(path: Path, *, override: bool) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key in os.environ and not override:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def parse_bool_env(*names: str, default: bool = False) -> bool:
    value = first_env(*names)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def parse_int_env(*names: str, default: int) -> int:
    value = first_env(*names, default=str(default))
    return int(value)


def parse_float_env(*names: str, default: float) -> float:
    value = first_env(*names, default=str(default))
    return float(value)


def normalize_llm_provider(value: str) -> str:
    provider = (value or "").strip().lower()
    if provider == "openai":
        return "openai_compat"
    return provider


def gemini_generate_url(model: str, explicit_url: str = "") -> str:
    if explicit_url.strip():
        return explicit_url.strip()
    return f"{GEMINI_BASE_URL}/{model}:generateContent"


def openai_chat_completions_url(*, url: str = "", base_url: str = "") -> str:
    if url.strip():
        return url.strip()
    clean_base = base_url.strip().rstrip("/")
    if not clean_base:
        return ""
    if clean_base.endswith("/chat/completions"):
        return clean_base
    return f"{clean_base}/chat/completions"


def read_llm_profile(
    prefix: str,
    *,
    default_provider: str,
    default_gemini_model: str,
    default_openai_model: str,
    inherit_global: bool = True,
    inherited_model_vars: Iterable[str] = (),
    inherited_provider_vars: Iterable[str] = (),
    inherited_url_vars: Iterable[str] = (),
    inherited_api_key_vars: Iterable[str] = (),
) -> LLMProfile:
    """Read a scoped LLM profile from environment variables.

    `prefix` should include the `_LLM` suffix for scoped profiles, for example
    `QUERY_PARSER_LLM` or `GRAPH_LLM`. Use `LLM` for the primary answer
    generation profile.
    """

    provider_names = [f"{prefix}_PROVIDER", *inherited_provider_vars]
    if inherit_global and prefix != "LLM":
        provider_names.append("LLM_PROVIDER")
    provider = normalize_llm_provider(
        first_env(*provider_names, default=default_provider)
    )

    model_names = [f"{prefix}_MODEL", *inherited_model_vars]
    if inherit_global and prefix != "LLM":
        model_names.append("LLM_MODEL")

    if provider == "gemini":
        model = first_env(
            *model_names,
            default=default_gemini_model,
        )
        api_key_names = [f"{prefix}_API_KEY", *inherited_api_key_vars]
        if inherit_global and prefix != "LLM":
            api_key_names.append("LLM_API_KEY")
        api_key = first_env(*api_key_names)
        url = first_env(
            f"{prefix}_URL",
            *inherited_url_vars,
            *((("LLM_URL",) if inherit_global and prefix != "LLM" else ())),
        )
        return LLMProfile(
            provider=provider,
            model=model,
            url=gemini_generate_url(model, url),
            api_key=api_key,
        )

    model = first_env(*model_names, default=default_openai_model)
    api_key_names = [f"{prefix}_API_KEY", *inherited_api_key_vars]
    if inherit_global and prefix != "LLM":
        api_key_names.append("LLM_API_KEY")
    api_key = first_env(*api_key_names)
    url = first_env(
        f"{prefix}_URL",
        *inherited_url_vars,
        *((("LLM_URL",) if inherit_global and prefix != "LLM" else ())),
    )
    base_url = first_env(
        f"{prefix}_BASE_URL",
        *((("LLM_BASE_URL",) if inherit_global and prefix != "LLM" else ())),
    )
    return LLMProfile(
        provider=provider,
        model=model,
        url=openai_chat_completions_url(url=url, base_url=base_url),
        api_key=api_key,
    )


def read_embedding_provider(prefix: str = "EMBEDDING") -> str:
    return normalize_llm_provider(
        first_env(f"{prefix}_PROVIDER", default="openai_compat")
    )


def read_embedding_model(default: str, prefix: str = "EMBEDDING") -> str:
    return first_env(f"{prefix}_MODEL", default=default)


def read_embedding_api_key(prefix: str = "EMBEDDING") -> str:
    return first_env(f"{prefix}_API_KEY")


def read_embedding_base_url(prefix: str = "EMBEDDING") -> str:
    return first_env(
        f"{prefix}_BASE_URL",
        default=DEFAULT_EMBEDDING_BASE_URL,
    ).rstrip("/")


def read_embedding_dimensions(prefix: str = "EMBEDDING") -> int | None:
    value = first_env(f"{prefix}_DIMENSIONS")
    return int(value) if value else None
