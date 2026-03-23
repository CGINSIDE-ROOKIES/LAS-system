from src.registry.validate_registry import validate_endpoint_registry



def test_related_registry_allows_enabled_html_only_whitelisted_endpoint():
    registry = {
        "registry_name": "endpoint_registry_related",
        "validation": {
            "enabled_html_only_whitelist": ["interpretation_detail"],
        },
        "endpoints": {
            "precedent_list": {
                "enabled": True,
                "path": "/lawSearch.do",
                "target": "prec",
                "required_params": ["OC"],
                "response_types": ["JSON"],
            },
            "precedent_detail": {
                "enabled": True,
                "path": "/lawService.do",
                "target": "prec",
                "required_params": ["OC", "ID"],
                "response_types": ["JSON"],
            },
            "constitutional_list": {
                "enabled": True,
                "path": "/lawSearch.do",
                "target": "detc",
                "required_params": ["OC"],
                "response_types": ["JSON"],
            },
            "constitutional_detail": {
                "enabled": True,
                "path": "/lawService.do",
                "target": "detc",
                "required_params": ["OC", "ID"],
                "response_types": ["JSON"],
            },
            "interpretation_list": {
                "enabled": True,
                "path": "/lawSearch.do",
                "target": "expc",
                "required_params": ["OC"],
                "response_types": ["JSON"],
            },
            "interpretation_detail": {
                "enabled": True,
                "path": "/lawService.do",
                "target": "expc",
                "required_params": ["OC", "ID"],
                "response_types": ["HTML"],
            },
            "admin_appeal_list": {
                "enabled": True,
                "path": "/lawSearch.do",
                "target": "decc",
                "required_params": ["OC"],
                "response_types": ["JSON"],
            },
            "admin_appeal_detail": {
                "enabled": True,
                "path": "/lawService.do",
                "target": "decc",
                "required_params": ["OC", "ID"],
                "response_types": ["JSON"],
            },
        },
    }

    result = validate_endpoint_registry(registry)

    assert result.has_errors is False
