from src.common.io_utils import _read_json, _write_json
from src.export.appendix_dataset_builder import (
    build_and_write_appendix_datasets,
    build_appendix_clean_records,
    build_appendix_raw_records,
    build_appendix_table_records,
)


def test_build_appendix_datasets_separates_clean_and_table_records(tmp_path):
    appendix_dir = tmp_path / "normalized" / "01_current_law_appendix" / "근로기준법"
    bundle_path = appendix_dir / "근로기준법__parsed_appendix.json"

    _write_json(
        bundle_path,
        {
            "law_name": "근로기준법",
            "law_id": "001",
            "appendix_count": 4,
            "appendix_type_counts": {
                "appendix_document": 1,
                "table_appendix": 1,
                "form_appendix": 1,
                "metadata_only": 1,
            },
            "appendix_records": [
                {
                    "id": "appendix::근로기준법::000100E",
                    "law_name": "근로기준법",
                    "law_id": "001",
                    "kind_name": "법률",
                    "appendix_key": "000100E",
                    "appendix_no": "0001",
                    "appendix_kind": "별표",
                    "appendix_type": "appendix_document",
                    "appendix_title": "해고 예고의 예외가 되는 근로자의 귀책사유",
                    "api_text_raw": "1. 첫째 줄\n2. 둘째 줄",
                    "api_text": "1. 첫째 줄 2. 둘째 줄",
                    "api_text_line_count": 2,
                    "table_signal_count": 0,
                    "form_signal_count": 0,
                    "has_substantive_text": True,
                    "has_table_markup": False,
                    "is_default_serving_candidate": True,
                    "download_assets": {},
                    "processing_policy": {
                        "recommended_next_step": "use_api_text_clean_as_primary"
                    },
                },
                {
                    "id": "appendix::근로기준법::000200E",
                    "law_name": "근로기준법",
                    "law_id": "001",
                    "kind_name": "법률",
                    "appendix_key": "000200E",
                    "appendix_no": "0002",
                    "appendix_kind": "별표",
                    "appendix_type": "table_appendix",
                    "appendix_title": "질환 분류표",
                    "api_text_raw": "┌─┬─┐\n│A│B│\n└─┴─┘",
                    "api_text": "┌─┬─┐ │A│B│ └─┴─┘",
                    "api_text_line_count": 3,
                    "table_signal_count": 9,
                    "form_signal_count": 0,
                    "has_substantive_text": True,
                    "has_table_markup": True,
                    "is_default_serving_candidate": False,
                    "download_assets": {},
                    "processing_policy": {
                        "recommended_next_step": "use_api_text_clean_then_reextract_pdf_if_layout_needed"
                    },
                },
                {
                    "id": "appendix::근로기준법::000300F",
                    "law_name": "근로기준법",
                    "law_id": "001",
                    "kind_name": "법률",
                    "appendix_key": "000300F",
                    "appendix_no": "0003",
                    "appendix_kind": "서식",
                    "appendix_type": "form_appendix",
                    "appendix_title": "근로조건 위반 손해배상 청구 신청서",
                    "api_text_raw": "접수번호 │ 처리기간\n신청인 (서명 또는 인)",
                    "api_text": "접수번호 │ 처리기간 신청인 (서명 또는 인)",
                    "api_text_line_count": 2,
                    "table_signal_count": 1,
                    "form_signal_count": 3,
                    "has_substantive_text": True,
                    "has_table_markup": False,
                    "is_default_serving_candidate": False,
                    "download_assets": {},
                    "processing_policy": {
                        "recommended_next_step": "use_api_text_clean_then_reextract_pdf_if_layout_needed"
                    },
                },
                {
                    "id": "appendix::근로기준법::000400E",
                    "law_name": "근로기준법",
                    "law_id": "001",
                    "kind_name": "법률",
                    "appendix_key": "000400E",
                    "appendix_no": "0004",
                    "appendix_kind": "별표",
                    "appendix_type": "metadata_only",
                    "appendix_title": "삭제",
                    "api_text_raw": None,
                    "api_text": None,
                    "api_text_line_count": 0,
                    "table_signal_count": 0,
                    "form_signal_count": 0,
                    "has_substantive_text": False,
                    "has_table_markup": False,
                    "is_default_serving_candidate": False,
                    "download_assets": {},
                    "processing_policy": {
                        "recommended_next_step": "metadata_only_keep_for_reference"
                    },
                },
            ],
        },
    )

    raw_records = build_appendix_raw_records(tmp_path / "normalized" / "01_current_law_appendix")
    clean_records = build_appendix_clean_records(tmp_path / "normalized" / "01_current_law_appendix")
    table_records = build_appendix_table_records(tmp_path / "normalized" / "01_current_law_appendix")

    assert len(raw_records) == 4
    assert len(clean_records) == 1
    assert len(table_records) == 2
    assert clean_records[0]["appendix_type"] == "appendix_document"
    assert "법령명: 근로기준법" in clean_records[0]["text"]
    assert "별표제목: 해고 예고의 예외가 되는 근로자의 귀책사유" in clean_records[0]["text"]

    manifest = build_and_write_appendix_datasets(
        normalized_appendix_base_dir=tmp_path / "normalized" / "01_current_law_appendix",
        output_dir=tmp_path / "dataset",
        max_chars=500,
        overlap=50,
    )

    assert manifest["appendix_raw_count"] == 4
    assert manifest["appendix_clean_count"] == 1
    assert manifest["appendix_table_count"] == 2
    assert _read_json(tmp_path / "dataset" / "appendix_dataset_manifest.json")["appendix_type_counts"]["form_appendix"] == 1


def test_build_appendix_table_records_prefers_asset_text_when_available(tmp_path):
    appendix_dir = tmp_path / "normalized" / "01_current_law_appendix" / "근로기준법"
    asset_dir = tmp_path / "normalized" / "01_current_law_appendix_assets" / "근로기준법"
    bundle_path = appendix_dir / "근로기준법__parsed_appendix.json"
    asset_bundle_path = asset_dir / "근로기준법__appendix_assets.parsed.json"

    _write_json(
        bundle_path,
        {
            "law_name": "근로기준법",
            "law_id": "001",
            "appendix_count": 1,
            "appendix_type_counts": {"table_appendix": 1},
            "appendix_records": [
                {
                    "id": "appendix::근로기준법::000200E",
                    "law_name": "근로기준법",
                    "law_id": "001",
                    "kind_name": "법률",
                    "appendix_key": "000200E",
                    "appendix_no": "0002",
                    "appendix_kind": "별표",
                    "appendix_type": "table_appendix",
                    "appendix_title": "질환 분류표",
                    "api_text_raw": "┌─┬─┐\n│A│B│\n└─┴─┘",
                    "api_text": "┌─┬─┐ │A│B│ └─┴─┘",
                    "api_text_line_count": 3,
                    "table_signal_count": 9,
                    "form_signal_count": 0,
                    "has_substantive_text": True,
                    "has_table_markup": True,
                    "is_default_serving_candidate": False,
                    "download_assets": {},
                    "processing_policy": {
                        "recommended_next_step": "use_api_text_clean_then_reextract_pdf_if_layout_needed"
                    },
                }
            ],
        },
    )

    _write_json(
        asset_bundle_path,
        {
            "law_name": "근로기준법",
            "appendix_asset_records": [
                {
                    "appendix_id": "appendix::근로기준법::000200E",
                    "appendix_key": "000200E",
                    "appendix_type": "table_appendix",
                    "appendix_title": "질환 분류표",
                    "downloaded_asset_count": 1,
                    "successful_extraction_count": 1,
                    "best_text_source": "pdf_text",
                    "best_text_reason": "table_or_form_prefers_pdf_when_available",
                    "best_text_raw": "PDF 표 본문\n질환명 질병코드\n감기 J00",
                    "best_text": "PDF 표 본문 질환명 질병코드 감기 J00",
                    "best_asset_local_path": "/tmp/sample_table.pdf",
                    "assets": [],
                }
            ],
        },
    )

    table_records = build_appendix_table_records(
        tmp_path / "normalized" / "01_current_law_appendix",
        normalized_appendix_asset_base_dir=tmp_path / "normalized" / "01_current_law_appendix_assets",
    )

    assert len(table_records) == 1
    assert table_records[0]["text_source"] == "pdf_text"
    assert "텍스트소스: pdf_text" in table_records[0]["text"]
    assert "PDF 표 본문" in table_records[0]["text"]
