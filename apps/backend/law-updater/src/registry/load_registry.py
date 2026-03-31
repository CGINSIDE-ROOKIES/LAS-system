from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from src.common.io_utils import _read_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config"


def _resolve_path(path_str: str | Path | None, default_filename: str) -> Path:
    if path_str is None:
        return DEFAULT_CONFIG_PATH / default_filename

    resolved = Path(path_str)
    if resolved.is_absolute():
        return resolved

    return PROJECT_ROOT / resolved


def _read_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"YAML config not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    if data is None:
        return {}

    if not isinstance(data, dict):
        raise ValueError(f"YAML config must be a mapping object: {path}")

    return data


def _apply_runtime_env_overrides(registry: dict[str, Any]) -> dict[str, Any]:
    runtime = registry.setdefault("runtime", {})

    env_api_base_url = os.getenv("LAW_API_BASE_URL")
    if env_api_base_url:
        runtime["api_base_url"] = env_api_base_url

    return registry


def load_collection_scope(path: str | Path | None = None) -> dict[str, Any]:
    scope_path = _resolve_path(path, "collection_scope.json")
    return _read_json(scope_path)


def load_endpoint_registry(path: str | Path | None = None) -> dict[str, Any]:
    registry_path = _resolve_path(path, "endpoint_registry_law.yaml")
    registry_data = _read_yaml_file(registry_path)
    return _apply_runtime_env_overrides(registry_data)