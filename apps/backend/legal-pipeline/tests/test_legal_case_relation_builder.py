from src.common.io_utils import _write_json, _write_jsonl
from src.export.legal_case_relation_builder import (
    build_case_reference_audit_records,
    build_case_to_case_relation_records,
)


def test_build_case_to_case_relation_records_resolves_referenced_doc_number(tmp_path):
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"

    source_detail_path = root / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(
        source_detail_path,
        {
            "판례일련번호": "123456",
            "사건명": "임금",
            "사건번호": "2019다12345",
            "선고일자": "2019.05.30",
            "판례내용": "이 사건은 2018다12345 판결의 법리와 근로기준법 제43조의2를 함께 참조하였다.",
        },
    )

    target_detail_path = root / "canonical" / "prec" / "case_prec_777777__detail.json"
    _write_json(
        target_detail_path,
        {
            "판례일련번호": "777777",
            "사건명": "선행판결",
            "사건번호": "2018다12345",
            "선고일자": "2018.04.20",
            "판례내용": "선행 판결 본문",
        },
    )

    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::prec::123456",
                "canonical_case_id": "case::prec::123456",
                "canonical_id": "case::prec::123456",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(source_detail_path),
            },
            {
                "id": "case::prec::777777",
                "canonical_case_id": "case::prec::777777",
                "canonical_id": "case::prec::777777",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "777777",
                "title": "선행판결",
                "doc_number": "2018다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(target_detail_path),
            },
        ],
    )

    records = build_case_to_case_relation_records(raw_related_base_dir=raw_dir)

    assert len(records) == 1
    record = records[0]
    assert record["relation_model"] == "case_to_case"
    assert record["relation_type"] == "cited_case"
    assert record["source_canonical_case_id"] == "case::prec::123456"
    assert record["target_canonical_case_id"] == "case::prec::777777"
    assert record["referenced_case_number"] == "2018다12345"
    assert record["resolution_status"] == "resolved"


def test_build_case_to_case_relation_records_skips_ambiguous_doc_number_matches(tmp_path):
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"

    source_detail_path = root / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(
        source_detail_path,
        {
            "판례일련번호": "123456",
            "사건명": "임금",
            "사건번호": "2019다12345",
            "선고일자": "2019.05.30",
            "판례내용": "이 사건은 2018다12345 판결의 법리를 인용하였다.",
        },
    )

    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::prec::123456",
                "canonical_case_id": "case::prec::123456",
                "canonical_id": "case::prec::123456",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(source_detail_path),
            },
            {
                "id": "case::prec::777777",
                "canonical_case_id": "case::prec::777777",
                "canonical_id": "case::prec::777777",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "777777",
                "title": "선행판결1",
                "doc_number": "2018다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": False,
                "detail_payload_path": None,
            },
            {
                "id": "case::prec::888888",
                "canonical_case_id": "case::prec::888888",
                "canonical_id": "case::prec::888888",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "888888",
                "title": "선행판결2",
                "doc_number": "2018다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": False,
                "detail_payload_path": None,
            },
        ],
    )

    records = build_case_to_case_relation_records(raw_related_base_dir=raw_dir)

    assert records == []


def test_build_case_reference_audit_records_tracks_ambiguous_and_unresolved(tmp_path):
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"

    source_detail_path = root / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(
        source_detail_path,
        {
            "판례일련번호": "123456",
            "사건명": "임금",
            "사건번호": "2019다12345",
            "선고일자": "2019.05.30",
            "판례내용": "이 사건은 2018다12345 판결과 2027다99999 판결을 함께 참조하였다.",
        },
    )

    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::prec::123456",
                "canonical_case_id": "case::prec::123456",
                "canonical_id": "case::prec::123456",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(source_detail_path),
            },
            {
                "id": "case::prec::777777",
                "canonical_case_id": "case::prec::777777",
                "canonical_id": "case::prec::777777",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "777777",
                "title": "선행판결1",
                "doc_number": "2018다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": False,
                "detail_payload_path": None,
            },
            {
                "id": "case::prec::888888",
                "canonical_case_id": "case::prec::888888",
                "canonical_id": "case::prec::888888",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "888888",
                "title": "선행판결2",
                "doc_number": "2018다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": False,
                "detail_payload_path": None,
            },
        ],
    )

    records = build_case_reference_audit_records(raw_related_base_dir=raw_dir)

    assert len(records) == 2
    by_ref = {record["referenced_case_number"]: record for record in records}
    assert by_ref["2018다12345"]["resolution_status"] == "ambiguous"
    assert by_ref["2018다12345"]["candidate_count"] == 2
    assert by_ref["2027다99999"]["resolution_status"] == "unresolved_external"
    assert by_ref["2027다99999"]["candidate_count"] == 0


def test_build_case_to_case_relation_records_uses_structured_reference_field(tmp_path):
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"

    source_detail_path = root / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(
        source_detail_path,
        {
            "PrecService": {
                "판례정보일련번호": "123456",
                "사건명": "임금",
                "사건번호": "2019다12345",
                "선고일자": "2019.05.30",
                "참조판례": "2018다12345",
                "판례내용": "본문에는 사건번호가 직접 나오지 않는다.",
            }
        },
    )

    target_detail_path = root / "canonical" / "prec" / "case_prec_777777__detail.json"
    _write_json(
        target_detail_path,
        {
            "PrecService": {
                "판례정보일련번호": "777777",
                "사건명": "선행판결",
                "사건번호": "2018다12345",
                "선고일자": "2018.04.20",
                "판례내용": "선행 판결 본문",
            }
        },
    )

    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::prec::123456",
                "canonical_case_id": "case::prec::123456",
                "canonical_id": "case::prec::123456",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(source_detail_path),
            },
            {
                "id": "case::prec::777777",
                "canonical_case_id": "case::prec::777777",
                "canonical_id": "case::prec::777777",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "777777",
                "title": "선행판결",
                "doc_number": "2018다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(target_detail_path),
            },
        ],
    )

    records = build_case_to_case_relation_records(raw_related_base_dir=raw_dir)

    assert len(records) == 1
    assert records[0]["referenced_case_number"] == "2018다12345"
