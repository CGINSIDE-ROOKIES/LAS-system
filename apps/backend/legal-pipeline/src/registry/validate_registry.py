from __future__ import annotations

from typing import Any

from src.models.registry_models import ValidationResult


LAW_REQUIRED_ENDPOINTS = {
    "law_system_diagram_list",
    "law_system_diagram_detail",
    "law_current_list",
    "law_current_detail",
    "law_current_article",
    "law_change_daily",
    "law_article_change_daily",
    "law_delete_daily",
}

RELATED_REQUIRED_ENDPOINTS = {
    "precedent_list",
    "precedent_detail",
    "constitutional_list",
    "constitutional_detail",
    "interpretation_list",
    "admin_appeal_list",
    "admin_appeal_detail",
}

# 하위 호환
REQUIRED_ENDPOINTS = LAW_REQUIRED_ENDPOINTS


def validate_collection_scope(scope: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    if "outputs" not in scope:
        result.add_error("collection_scope", "Missing 'outputs' field")
        return result

    outputs = scope["outputs"]

    if not isinstance(outputs, list):
        result.add_error("collection_scope.outputs", "Must be a list")
        return result

    file_ids = set()

    for i, output in enumerate(outputs):
        path = f"collection_scope.outputs[{i}]"

        if not isinstance(output, dict):
            result.add_error(path, "Output config must be a dict")
            continue

        if "file_id" not in output:
            result.add_error(path, "Missing 'file_id'")
        else:
            file_ids.add(output["file_id"])

        if "file_name" not in output:
            result.add_error(path, "Missing 'file_name'")

        if "unit_type" not in output:
            result.add_error(path, "Missing 'unit_type'")

    if "01_current_law" not in file_ids:
        result.add_error(
            "collection_scope.outputs",
            "Missing required output with file_id '01_current_law'",
        )

    return result


def _get_required_endpoints(registry: dict[str, Any]) -> set[str]:
    registry_name = str(registry.get("registry_name") or "").strip()

    if registry_name == "endpoint_registry_related":
        return RELATED_REQUIRED_ENDPOINTS

    return LAW_REQUIRED_ENDPOINTS


def _validate_response_types(
    result: ValidationResult,
    path: str,
    endpoint: dict[str, Any],
    require_json_capable_for_enabled: bool,
    allow_html_only_if_enabled_false: bool,
) -> None:
    enabled = bool(endpoint.get("enabled", False))
    response_types = endpoint.get("response_types", [])

    if response_types is None:
        response_types = []

    if not isinstance(response_types, list):
        result.add_error(path, "'response_types' must be a list")
        return

    normalized = {
        str(item).strip().upper()
        for item in response_types
        if str(item).strip()
    }

    if require_json_capable_for_enabled and enabled and "JSON" not in normalized:
        result.add_error(
            path,
            "Enabled endpoint must support JSON response",
        )

    if allow_html_only_if_enabled_false and enabled and normalized == {"HTML"}:
        result.add_error(
            path,
            "Enabled endpoint cannot be HTML-only",
        )


def validate_endpoint_registry(registry: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    if "endpoints" not in registry:
        result.add_error("registry", "Missing 'endpoints'")
        return result

    endpoints = registry["endpoints"]

    if not isinstance(endpoints, dict):
        result.add_error("registry.endpoints", "Must be a mapping of objects")
        return result

    validation = registry.get("validation", {})
    if not isinstance(validation, dict):
        validation = {}

    require_json_capable_for_enabled = bool(
        validation.get("require_json_capable_for_enabled", True)
    )
    allow_html_only_if_enabled_false = bool(
        validation.get("allow_html_only_if_enabled_false", True)
    )

    required_endpoints = _get_required_endpoints(registry)

    for key in required_endpoints:
        if key not in endpoints:
            result.add_error(
                "registry.endpoints",
                f"Missing required endpoint '{key}'",
            )

    for name, endpoint in endpoints.items():
        path = f"registry.endpoints.{name}"

        if not isinstance(endpoint, dict):
            result.add_error(path, "Endpoint config must be a dict")
            continue

        enabled = bool(endpoint.get("enabled", False))

        if "path" not in endpoint:
            result.add_error(path, "Missing 'path'")

        # disabled optional endpoint는 최소 구조만 허용
        if not enabled and name not in required_endpoints:
            continue

        if "target" not in endpoint:
            result.add_error(path, "Missing 'target'")

        if "required_params" not in endpoint:
            result.add_error(path, "Missing 'required_params'")
        elif not isinstance(endpoint.get("required_params"), list):
            result.add_error(path, "'required_params' must be a list")

        _validate_response_types(
            result=result,
            path=path,
            endpoint=endpoint,
            require_json_capable_for_enabled=require_json_capable_for_enabled,
            allow_html_only_if_enabled_false=allow_html_only_if_enabled_false,
        )

    return result