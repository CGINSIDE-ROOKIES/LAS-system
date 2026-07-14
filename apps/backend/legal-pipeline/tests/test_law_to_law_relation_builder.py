from src.common.io_utils import _write_json
from src.export.law_to_law_relation_builder import (
    _is_valid_law_name,
    build_law_to_law_relation_records,
)


def test_build_law_to_law_relation_records_extracts_explicit_law_and_article_refs(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"

    _write_json(
        normalized_dir / "근로기준법_시행규칙__parsed_law.json",
        {
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
            "ef_yd": "20250223",
            "kind_name": "고용노동부령",
            "classified_level": "시행규칙",
            "articles": [
                {
                    "article_key": "16",
                    "article_no": "제16조",
                    "article_no_display": "제16조",
                    "article_title": "서식",
                    "article_title_raw": "서식",
                    "article_text": "근로기준법 제28조 및 근로기준법 시행령 제11조에 따른다.",
                    "article_text_raw": "근로기준법 제28조 및 근로기준법 시행령 제11조에 따른다.",
                }
            ],
        },
    )
    _write_json(
        normalized_dir / "근로기준법__parsed_law.json",
        {
            "law_name": "근로기준법",
            "law_id": "001872",
            "mst": "269390",
            "articles": [],
        },
    )
    _write_json(
        normalized_dir / "근로기준법_시행령__parsed_law.json",
        {
            "law_name": "근로기준법 시행령",
            "law_id": "006860",
            "mst": "269394",
            "articles": [],
        },
    )

    rows = build_law_to_law_relation_records(tmp_path / "normalized" / "01_current_law")

    assert len(rows) == 2
    rows_by_target = {row["law_name"]: row for row in rows}

    law_row = rows_by_target["근로기준법"]
    assert law_row["relation_model"] == "law_to_law"
    assert law_row["relation_type"] == "related_law"
    assert law_row["law_uid"] == "001872"
    assert law_row["source_law_uid"] == "006859"
    assert law_row["article_keys"] == ["28"]
    assert law_row["article_no_displays"] == ["제28조"]
    assert "근로기준법 시행규칙" in law_row["text"]
    assert law_row["search_text"] == law_row["text"]
    assert law_row["display_text"]

    decree_row = rows_by_target["근로기준법 시행령"]
    assert decree_row["relation_model"] == "law_to_law"
    assert decree_row["article_keys"] == ["11"]
    assert decree_row["article_no_displays"] == ["제11조"]


def test_build_law_to_law_relation_records_extracts_same_law_and_external_refs(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"

    _write_json(
        normalized_dir / "근로기준법__parsed_law.json",
        {
            "law_name": "근로기준법",
            "law_id": "001872",
            "mst": "269390",
            "ef_yd": "20250223",
            "kind_name": "법률",
            "classified_level": "법",
            "articles": [
                {
                    "article_key": "3",
                    "article_no": "제3조",
                    "article_no_display": "제3조",
                    "article_title": "정의",
                    "article_title_raw": "정의",
                    "article_text": "정의를 정한다.",
                    "article_text_raw": "정의를 정한다.",
                },
                {
                    "article_key": "4",
                    "article_no": "제4조",
                    "article_no_display": "제4조",
                    "article_title": "근로조건",
                    "article_title_raw": "근로조건",
                    "article_text": "전조 및 민법 제750조를 따른다.",
                    "article_text_raw": "전조 및 민법 제750조를 따른다.",
                },
            ],
        },
    )

    rows = build_law_to_law_relation_records(tmp_path / "normalized" / "01_current_law")
    rows_by_target = {row["law_name"]: row for row in rows}

    same_law_row = rows_by_target["근로기준법"]
    assert same_law_row["source_law_uid"] == same_law_row["law_uid"]
    assert "same_law_reference" in same_law_row["relation_types"]
    assert "relative_reference" in same_law_row["relation_types"]
    assert same_law_row["article_keys"] == ["3"]
    assert same_law_row["source_article_key"] == "4"
    assert same_law_row["resolution_status"] == "resolved"
    assert same_law_row["reference_texts"] == ["전조"]

    external_row = rows_by_target["민법"]
    assert external_row["law_uid"] is None
    assert external_row["relation_type"] == "related_law"
    assert "external_reference" in external_row["relation_types"]
    assert external_row["article_keys"] == ["750"]
    assert external_row["resolution_status"] == "unresolved_external"


def test_build_law_to_law_relation_records_recovers_noisy_scope_reference_as_family_law(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "건설산업기본법"

    _write_json(
        normalized_dir / "건설산업기본법_시행령__parsed_law.json",
        {
            "law_name": "건설산업기본법 시행령",
            "law_id": "002115",
            "mst": "269999",
            "ef_yd": "20250223",
            "kind_name": "대통령령",
            "classified_level": "시행령",
            "articles": [
                {
                    "article_key": "43",
                    "article_no": "제43조",
                    "article_no_display": "제43조",
                    "article_title": "하도급계약의 특례",
                    "article_title_raw": "하도급계약의 특례",
                    "article_text": "제43조(하도급계약의 특례) 법 제48조에 따른다.",
                    "article_text_raw": "제43조(하도급계약의 특례) 법 제48조에 따른다.",
                }
            ],
        },
    )
    _write_json(
        normalized_dir / "건설산업기본법__parsed_law.json",
        {
            "law_name": "건설산업기본법",
            "law_id": "000261",
            "mst": "269998",
            "articles": [],
        },
    )

    rows = build_law_to_law_relation_records(tmp_path / "normalized" / "01_current_law")

    assert len(rows) == 1
    row = rows[0]
    assert row["law_name"] == "건설산업기본법"
    assert row["article_keys"] == ["48"]
    assert row["resolution_status"] == "resolved"
    assert "relative_reference" in row["relation_types"]


class TestIsValidLawName:
    """이슈 K: 의미 없는 법령명 파편 필터."""

    def test_rejects_single_char_variants(self):
        assert _is_valid_law_name("동법") is False

    def test_rejects_particle_fragment_ending_with_space_법(self):
        assert _is_valid_law_name("따라 법") is False
        assert _is_valid_law_name("경우 법") is False
        assert _is_valid_law_name("이란 법") is False
        assert _is_valid_law_name("란 법") is False
        assert _is_valid_law_name("투자설명서상 법") is False
        assert _is_valid_law_name("하수급인에게 법") is False

    def test_allows_real_law_names(self):
        assert _is_valid_law_name("근로기준법") is True
        assert _is_valid_law_name("민법") is True  # 2글자지만 실제 법령명
        assert _is_valid_law_name("체육시설의 설치·이용에 관한 법률") is True
        assert _is_valid_law_name("근로자퇴직급여 보장법") is True

    def test_allows_에관한_ending_law(self):
        assert _is_valid_law_name("건강 및 안전에 관한 법") is True


def test_build_law_to_law_records_root_law_uid_with_middle_dot_directory(tmp_path):
    """이슈 J: 디렉토리명 복원 시 중점 소실로 root_law_uid가 null이 되는 버그 수정."""
    # 디렉토리명은 _safe_filename 으로 생성 → ·(U+00B7) → _
    normalized_dir = (
        tmp_path / "normalized" / "01_current_law"
        / "남녀고용평등과_일_가정_양립_지원에_관한_법률"
    )

    # 페이로드의 law_name은 ·(또는 ㆍ) 포함
    _write_json(
        normalized_dir / "남녀고용평등과_일_가정_양립_지원에_관한_법률__parsed_law.json",
        {
            "law_name": "남녀고용평등과 일·가정 양립 지원에 관한 법률",
            "law_id": "003881",
            "mst": "271000",
            "ef_yd": "20250101",
            "kind_name": "법률",
            "classified_level": "법",
            "articles": [
                {
                    "article_key": "19",
                    "article_no": "제19조",
                    "article_no_display": "제19조",
                    "article_title": "육아휴직",
                    # 법령명 명시 참조 → same_law_reference row 생성
                    "article_text_raw": "남녀고용평등과 일·가정 양립 지원에 관한 법률 제20조에 따른 육아휴직을 보장한다.",
                }
            ],
        },
    )

    rows = build_law_to_law_relation_records(tmp_path / "normalized" / "01_current_law")

    # same_law_reference 행이 생성되며 root_law_uid가 null이 아니어야 한다
    assert len(rows) >= 1
    assert all(row["root_law_uid"] is not None for row in rows), \
        "root_law_uid null: 디렉토리명 복원 시 중점 소실 버그"


def test_build_law_to_law_records_filters_noisy_external_law_names(tmp_path):
    """이슈 K: 파서가 추출한 의미 없는 법령명 파편이 law_to_law에 포함되지 않아야 한다."""
    normalized_dir = (
        tmp_path / "normalized" / "01_current_law" / "근로기준법"
    )

    _write_json(
        normalized_dir / "근로기준법__parsed_law.json",
        {
            "law_name": "근로기준법",
            "law_id": "001872",
            "mst": "269390",
            "ef_yd": "20250101",
            "kind_name": "법률",
            "classified_level": "법",
            "articles": [
                {
                    "article_key": "1",
                    "article_no": "제1조",
                    "article_no_display": "제1조",
                    "article_title": "목적",
                    # "따라 법 제3조" 형태의 파편이 포함된 텍스트
                    "article_text_raw": "이 법은 민법 제750조 및 따라 법 제3조에 따른다.",
                }
            ],
        },
    )

    rows = build_law_to_law_relation_records(tmp_path / "normalized" / "01_current_law")

    law_names = {row["law_name"] for row in rows}
    assert "따라 법" not in law_names, '"따라 법" 파편이 법령 관계에 포함됨'
