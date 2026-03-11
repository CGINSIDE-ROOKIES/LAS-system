from __future__ import annotations

from typing import Any

from src.models.registry_models import RequestSpec

def _require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name}, must be dict")
    return value

def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

def _resolve_response_type(
        runtime: dict[str, Any],
        endpoint: dict[str, Any],
) -> str:
    endpoint_preferred = endpoint.get("preferred_type")
    runtime_preferred = runtime.get("preferred_type")

    response_type = endpoint_preferred or runtime_preferred
    return str(response_type).upper()

def _build_params(
    runtime: dict[str, Any],
    endpoint: dict[str, Any],
    runtime_params: dict[str, Any],
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    default_params = endpoint.get("default_params", {})
    if not isinstance(default_params, dict):
        raise ValueError("endpoint.default_params must be a dict")

    params.update(default_params)
    params.update(runtime_params)

    auth_param = runtime.get("auth_param", "OC")
    target = endpoint.get("effective_target", endpoint.get("target"))
    response_type = _resolve_response_type(runtime, endpoint)

    if target is not None:
        params.setdefault("target", target)

    params.setdefault("type", response_type)

    # auth value는 자동 생성하지 않고, runtime_params로 받아야 함
    if auth_param in runtime_params:
        params[auth_param] = runtime_params[auth_param]

    return params

def _validate_required_params(
    endpoint_key: str,
    endpoint: dict[str, Any],
    params: dict[str, Any],
) -> None:
    required_params = endpoint.get("required_params", [])
    if not isinstance(required_params, list):
        raise ValueError(
            f"endpoints.{endpoint_key}.required_params must be a list"
        )

    missing = [key for key in required_params if key not in params]
    if missing:
        raise ValueError(
            f"Missing required params for '{endpoint_key}': {missing}"
        )

def _validate_one_of_params(
    endpoint_key: str,
    endpoint: dict[str, Any],
    params: dict[str, Any],
) -> None:
    groups = endpoint.get("one_of_params", [])
    if not groups:
        return

    if not isinstance(groups, list):
        raise ValueError(
            f"endpoints.{endpoint_key}.one_of_params must be a list"
        )

    for group in groups:
        if not isinstance(group, list):
            raise ValueError(
                f"endpoints.{endpoint_key}.one_of_params items must be lists"
            )

        if not any(key in params for key in group):
            raise ValueError(
                f"Endpoint '{endpoint_key}' requires one of {group}"
            )

def _validate_one_of_param_groups(
    endpoint_key: str,
    endpoint: dict[str, Any],
    params: dict[str, Any],
) -> None:
    groups = endpoint.get("one_of_param_groups", [])
    if not groups:
        return

    if not isinstance(groups, list):
        raise ValueError(
            f"endpoints.{endpoint_key}.one_of_param_groups must be a list"
        )

    for group in groups:
        if not isinstance(group, list):
            raise ValueError(
                f"endpoints.{endpoint_key}.one_of_param_groups items must be lists"
            )

    if not any(all(key in params for key in group) for group in groups):
        raise ValueError(
            f"Endpoint '{endpoint_key}' requires one complete group from {groups}"
        )

def _validate_conditional_required(
    endpoint_key: str,
    endpoint: dict[str, Any],
    params: dict[str, Any],
) -> None:
    rules = endpoint.get("conditional_required", [])
    if not rules:
        return

    if not isinstance(rules, list):
        raise ValueError(
            f"endpoints.{endpoint_key}.conditional_required must be a list"
        )

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(
                f"endpoints.{endpoint_key}.conditional_required[{i}] must be a dict"
            )

        if_param = rule.get("if_param")
        then_required = rule.get("then_required", [])

        if if_param in params:
            missing = [key for key in then_required if key not in params]
            if missing:
                raise ValueError(
                    f"Endpoint '{endpoint_key}' requires {missing} when '{if_param}' is provided"
                )

def build_request(
    registry: dict[str, Any],
    endpoint_key: str,
    runtime_params: dict[str, Any] | None = None,
) -> RequestSpec:
    runtime_params = runtime_params or {}

    runtime = _require_dict(registry.get("runtime"), "registry.runtime")
    endpoints = _require_dict(registry.get("endpoints"), "registry.endpoints")

    if endpoint_key not in endpoints:
        raise KeyError(f"Unknown endpoint_key: {endpoint_key}")

    endpoint = _require_dict(
        endpoints[endpoint_key],
        f"registry.endpoints.{endpoint_key}",
    )

    if not endpoint.get("enabled", False):
        raise ValueError(f"Endpoint '{endpoint_key}' is disabled")

    base_url = runtime.get("api_base_url")
    path = endpoint.get("path")

    if not base_url:
        raise ValueError("registry.runtime.api_base_url is missing")
    if not path:
        raise ValueError(f"endpoints.{endpoint_key}.path is missing")

    url = _join_url(str(base_url), str(path))
    params = _build_params(runtime, endpoint, runtime_params)

    _validate_required_params(endpoint_key, endpoint, params)
    _validate_one_of_params(endpoint_key, endpoint, params)
    _validate_one_of_param_groups(endpoint_key, endpoint, params)
    _validate_conditional_required(endpoint_key, endpoint, params)

    timeout_sec = int(runtime.get("timeout_sec", 30))

    return RequestSpec(
        method="GET",
        url=url,
        params=params,
        timeout_sec=timeout_sec,
    )