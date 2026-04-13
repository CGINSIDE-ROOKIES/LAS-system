from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

_DOTENV_LOADED = False


def ensure_local_env_loaded() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True

    package_root = Path(__file__).resolve().parents[2]
    package_env = package_root / ".env"
    cwd_env = Path.cwd() / ".env"

    if load_dotenv is not None:
        if package_env.exists():
            load_dotenv(package_env, override=False)
        if cwd_env.exists() and cwd_env != package_env:
            load_dotenv(cwd_env, override=False)
        return

    _load_simple_env_file(package_env)
    if cwd_env.exists() and cwd_env != package_env:
        _load_simple_env_file(cwd_env)


def _load_simple_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
