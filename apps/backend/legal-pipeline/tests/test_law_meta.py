"""tests for src/common/law_meta.py"""

import pytest
from src.common.law_meta import build_law_uid, normalize_identifier_token


class TestNormalizeIdentifierToken:
    def test_middle_dot_variants_produce_same_token(self):
        # U+00B7 (·) vs U+318D (ㆍ) must yield identical output
        a = normalize_identifier_token("남녀고용평등과 일·가정 양립 지원에 관한 법률")
        b = normalize_identifier_token("남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률")
        assert a == b

    def test_spaces_replaced_with_underscore(self):
        assert normalize_identifier_token("법률 이름") == "법률_이름"

    def test_double_colon_replaced_with_dash(self):
        assert normalize_identifier_token("a::b") == "a-b"

    def test_empty_returns_unknown(self):
        assert normalize_identifier_token("") == "unknown"
        assert normalize_identifier_token(None) == "unknown"


class TestBuildLawUid:
    def test_middle_dot_variants_produce_same_uid(self):
        uid_a = build_law_uid(None, None, "남녀고용평등과 일·가정 양립 지원에 관한 법률")
        uid_b = build_law_uid(None, None, "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률")
        assert uid_a == uid_b

    def test_law_id_takes_priority_over_law_name(self):
        uid = build_law_uid("123456", None, "어떤 법률")
        assert uid == "123456"

    def test_all_none_returns_unknown_law(self):
        assert build_law_uid(None, None, None) == "unknown-law"
