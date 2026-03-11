from __future__ import annotations

from typing import Any

from src.models.registry_models import ValidationResult

REQUIRED_ENDPOINTS = {
    "law_system_diagram_list",
    "law_system_diagram_detail",
    "law_current_list",
    "law_current_detail",
    "law_current_article",
    "law_change_daily",
    "law_article_change_daily",
    "law_delete_daily",
}

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

def validate_endpoint_registry(registry: dict[str, Any]) -> ValidationResult:
    result = ValidationResult()

    if "endpoints" not in registry:
        result.add_error("registry", "Missing 'endpoints'")
        return result
    
    endpoints = registry["endpoints"]

    if not isinstance(endpoints, dict):
        result.add_error("registry.endpoints", "Must be a mapping of objects")
        return result
    
    # 필수 endpoint 검사
    for key in REQUIRED_ENDPOINTS:
        if key not in endpoints:
            result.add_error(
                "registry.endpoints",
                f"Missing required endpoint '{key}'",
            )
    
    # endpoint 구조 검사
    for name, endpoint in endpoints.items():
        path = f"registry.endpoints.{name}"

        if not isinstance(endpoint, dict):
            result.add_error(path, "Endpoint config must be a dict")
            continue

        if "path" not in endpoint:
            result.add_error(path, "Missing 'path'")
        
        if "target" not in endpoint:
            result.add_error(path, "Missing 'target'")

        if "required_params" not in endpoint:
            result.add_error(path, "Missing 'required_params'")

        #JSON 정책 검사
        enabled = endpoint.get("enabled", False)
        response_types = endpoint.get("response_type", [])

        if enabled and "JSON" in response_types:
            result.add_error(
                path,
                "Enabled endpoint must support JOSN response",
            )

    return result