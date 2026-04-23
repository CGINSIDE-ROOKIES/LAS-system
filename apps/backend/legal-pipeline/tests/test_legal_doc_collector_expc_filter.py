"""expc early pruning: _extract_expc_keyword / _is_relevant_expc_item 단위 테스트"""

import pytest
from src.collector.legal_doc_collector import _extract_expc_keyword, _is_relevant_expc_item


class TestExtractExpcKeyword:
    def test_strips_enforcement_decree_suffix(self):
        assert _extract_expc_keyword("근로기준법 시행령") == "근로기준법"

    def test_strips_enforcement_rule_suffix(self):
        assert _extract_expc_keyword("근로기준법 시행규칙") == "근로기준법"

    def test_strips_규칙_suffix(self):
        assert _extract_expc_keyword("어떤법 규칙") == "어떤법"

    def test_no_suffix_returns_first_token(self):
        assert _extract_expc_keyword("남녀고용평등과 일·가정 양립 지원에 관한 법률") == "남녀고용평등과"

    def test_single_word_law_name(self):
        assert _extract_expc_keyword("근로기준법") == "근로기준법"

    def test_enforcement_regulation_suffix(self):
        assert _extract_expc_keyword("고용보험법 시행규정") == "고용보험법"


class TestIsRelevantExpcItem:
    def test_keyword_in_title_returns_true(self):
        item = {"안건명": "민원인 - 근로기준법 제17조 관련 질의"}
        assert _is_relevant_expc_item(item, "근로기준법 시행령") is True

    def test_keyword_in_guillemet_title_returns_true(self):
        item = {"안건명": "민원인 - (「근로기준법」 제17조 관련)"}
        assert _is_relevant_expc_item(item, "근로기준법") is True

    def test_unrelated_title_returns_false(self):
        item = {"안건명": "민원인 - 체육시설의 설치·이용에 관한 법률 제31조 관련"}
        assert _is_relevant_expc_item(item, "근로기준법 시행령") is False

    def test_empty_title_passes_through(self):
        # 제목 없는 항목은 하위 단계에서 처리하도록 통과
        item = {"안건명": ""}
        assert _is_relevant_expc_item(item, "근로기준법") is True

    def test_missing_title_passes_through(self):
        item = {}
        assert _is_relevant_expc_item(item, "근로기준법") is True

    def test_long_law_name_uses_first_token(self):
        item = {"안건명": "남녀고용평등과 일·가정 양립 지원에 관한 법률 제19조 관련"}
        assert _is_relevant_expc_item(item, "남녀고용평등과 일·가정 양립 지원에 관한 법률") is True

    def test_non_expc_keyword_not_in_long_law_title_returns_false(self):
        item = {"안건명": "산업안전보건법 제36조 관련 질의"}
        assert _is_relevant_expc_item(item, "남녀고용평등과 일·가정 양립 지원에 관한 법률") is False
