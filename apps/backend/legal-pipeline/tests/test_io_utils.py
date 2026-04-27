"""io_utils 단위 테스트 — _safe_filename 중점 정규화 (이슈 H)."""

from src.common.io_utils import _safe_filename


class TestSafeFilename:
    def test_middle_dot_u00b7_becomes_underscore(self):
        assert _safe_filename("남녀고용평등과 일·가정") == "남녀고용평등과_일_가정"

    def test_korean_interpunct_u318d_also_becomes_underscore(self):
        # U+318D (ㆍ) 이전에는 \w 매치로 보존됐음 — 정규화 후 동일 결과
        assert _safe_filename("남녀고용평등과 일ㆍ가정") == "남녀고용평등과_일_가정"

    def test_both_variants_produce_same_result(self):
        a = _safe_filename("남녀고용평등과 일·가정 양립 지원에 관한 법률")
        b = _safe_filename("남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률")
        assert a == b, "· 와 ㆍ 가 다른 파일명을 생성해 경로 분기 발생"

    def test_space_only_variant_same_as_dot_variants(self):
        a = _safe_filename("남녀고용평등과 일 가정 양립 지원에 관한 법률")
        b = _safe_filename("남녀고용평등과 일·가정 양립 지원에 관한 법률")
        assert a == b

    def test_normal_law_names_unchanged(self):
        assert _safe_filename("근로기준법") == "근로기준법"
        assert _safe_filename("건설산업기본법 시행령") == "건설산업기본법_시행령"
