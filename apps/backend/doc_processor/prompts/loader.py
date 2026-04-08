"""Prompt loader for markdown prompt profiles."""

from __future__ import annotations

from pathlib import Path

_CACHE: dict[tuple[str, str], str] = {}


def _prompt_path(profile: str, key: str) -> Path:
    root = Path(__file__).resolve().parent
    return root / profile / f"{key}.md"


def load_prompt(
    key: str,
    *,
    profile: str = "default",
    reload: bool = False,
) -> str:
    """Load markdown prompt by `profile/key`."""
    cache_key = (profile, key)
    if not reload and cache_key in _CACHE:
        return _CACHE[cache_key]

    path = _prompt_path(profile, key)
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt not found: profile='{profile}', key='{key}', path='{path}'"
        )

    content = path.read_text(encoding="utf-8")
    _CACHE[cache_key] = content
    return content


__all__ = ["load_prompt"]
