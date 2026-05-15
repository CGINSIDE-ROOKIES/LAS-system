from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_LOADED = False


def backend_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_backend_env() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    load_dotenv(backend_root() / ".env", override=False)


def env_bool(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "y", "yes", "on"}
