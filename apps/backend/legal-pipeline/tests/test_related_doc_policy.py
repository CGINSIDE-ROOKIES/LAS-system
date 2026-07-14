from src.collector.legal_doc_collector import (
    get_family_law_entries,
    resolve_selected_targets,
    should_exclude_doc_item,
)


def test_resolve_selected_targets_uses_scope_and_skips_unsupported_target():
    scope = {
        "outputs": [
            {
                "file_id": "02_related_legal_docs",
                "doc_types": ["prec", "expc"],
                "include_law_family_levels": ["법", "시행령", "시행규칙"],
                "exclude_doc_kinds": ["예규", "훈령", "고시"],
            }
        ]
    }
    registry = {
        "endpoints": {
            "precedent_list": {"enabled": True},
            "interpretation_list": {"enabled": True},
        }
    }

    selected, skipped = resolve_selected_targets(scope, registry, explicit_targets=["prec", "expc", "legacy_target"])

    assert selected == ["prec", "expc"]
    assert skipped == [{"target": "legacy_target", "reason": "unsupported_target"}]


def test_get_family_law_entries_filters_by_classified_level():
    family_result = {
        "laws": [
            {"law_name": "근로기준법", "classified_level": "법"},
            {"law_name": "근로기준법 시행령", "classified_level": "시행령"},
            {"law_name": "행정규칙 예시", "classified_level": "기타"},
        ]
    }

    result = get_family_law_entries(
        family_result,
        allowed_levels={"법", "시행령", "시행규칙"},
    )

    names = [item["law_name"] for item in result]
    assert names == ["근로기준법", "근로기준법 시행령"]


def test_should_exclude_doc_item_by_doc_kind():
    item = {
        "사건명": "예시",
        "사건번호": "123",
        "문서종류": "예규",
    }

    assert should_exclude_doc_item(item, {"예규", "훈령", "고시"}) is True
