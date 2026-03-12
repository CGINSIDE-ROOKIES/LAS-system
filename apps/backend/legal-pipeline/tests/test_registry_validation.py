import pytest

from src.registry.validate_registry import validate_endpoint_registry


def _endpoint(path: str):
    return {
        "enabled": True,
        "path": path,
        "target": "law",
        "required_params": ["OC"],
        "response_types": ["JSON"],
    }


def test_registry_validation_success():
    registry = {
        "endpoints": {
            "law_system_diagram_list": _endpoint("/lawSystemDiagramList.do"),
            "law_system_diagram_detail": _endpoint("/lawSystemDiagramDetail.do"),
            "law_current_list": _endpoint("/lawSearch.do"),
            "law_current_detail": _endpoint("/lawService.do"),
            "law_current_article": _endpoint("/lawJosubService.do"),
            "law_change_daily": _endpoint("/lsHstInf.do"),
            "law_article_change_daily": _endpoint("/lsJoHstInf.do"),
            "law_delete_daily": _endpoint("/delHst.do"),
        }
    }

    result = validate_endpoint_registry(registry)

    assert result.has_errors is False


def test_registry_validation_missing_json_should_error():
    registry = {
        "endpoints": {
            "law_system_diagram_list": {
                **_endpoint("/lawSystemDiagramList.do"),
                "response_types": [],
            },
            "law_system_diagram_detail": _endpoint("/lawSystemDiagramDetail.do"),
            "law_current_list": _endpoint("/lawSearch.do"),
            "law_current_detail": _endpoint("/lawService.do"),
            "law_current_article": _endpoint("/lawJosubService.do"),
            "law_change_daily": _endpoint("/lsHstInf.do"),
            "law_article_change_daily": _endpoint("/lsJoHstInf.do"),
            "law_delete_daily": _endpoint("/delHst.do"),
        }
    }

    result = validate_endpoint_registry(registry)

    assert result.has_errors is True
    assert any("JSON" in issue.message for issue in result.issues)


def test_registry_validation_disabled_optional_endpoint_minimal_allowed():
    registry = {
        "endpoints": {
            "law_system_diagram_list": _endpoint("/lawSystemDiagramList.do"),
            "law_system_diagram_detail": _endpoint("/lawSystemDiagramDetail.do"),
            "law_current_list": _endpoint("/lawSearch.do"),
            "law_current_detail": _endpoint("/lawService.do"),
            "law_current_article": _endpoint("/lawJosubService.do"),
            "law_change_daily": _endpoint("/lsHstInf.do"),
            "law_article_change_daily": _endpoint("/lsJoHstInf.do"),
            "law_delete_daily": _endpoint("/delHst.do"),
            "optional_html_debug": {
                "enabled": False,
                "path": "/debug.do",
            },
        }
    }

    result = validate_endpoint_registry(registry)

    assert result.has_errors is False