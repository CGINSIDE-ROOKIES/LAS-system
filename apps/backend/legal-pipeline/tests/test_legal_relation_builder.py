import json
from pathlib import Path

from src.common.io_utils import _write_json, _write_jsonl
from src.export.legal_relation_builder import (
    _is_unverified_search_hit,
    build_legal_relation_records,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "legal_case"



def test_build_legal_relation_records_dedupes_by_case_and_law(tmp_path):
    payload = json.loads((FIXTURE_DIR / "prec_detail.json").read_text(encoding="utf-8"))
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"

    # root 1: 근로기준법과 시행령 모두 같은 case를 검색 hit
    root1 = raw_dir / "근로기준법"
    detail_path1 = root1 / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(detail_path1, payload)
    _write_jsonl(
        root1 / "candidate_hits.jsonl",
        [
            {
                "candidate_id": "cand1",
                "canonical_case_id": "case::prec::123456",
                "target": "prec",
                "source_law_name": "근로기준법",
                "source_law_uid": "law-001",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_file_path": "list1.json",
            },
            {
                "candidate_id": "cand2",
                "canonical_case_id": "case::prec::123456",
                "target": "prec",
                "source_law_name": "근로기준법 시행령",
                "source_law_uid": "law-002",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_file_path": "list2.json",
            },
        ],
    )
    _write_jsonl(
        root1 / "canonical_cases.jsonl",
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
                "source_law_names": ["근로기준법", "근로기준법 시행령"],
                "source_law_uids": ["law-001", "law-002"],
                "source_hit_count": 2,
                "detail_available": True,
                "detail_payload_path": str(detail_path1),
            }
        ],
    )

    # root 2: 같은 case가 다시 근로기준법으로 검색 hit -> 같은 relation row에 merge되어야 함
    root2 = raw_dir / "최저임금법"
    detail_path2 = root2 / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(detail_path2, payload)
    _write_jsonl(
        root2 / "candidate_hits.jsonl",
        [
            {
                "candidate_id": "cand3",
                "canonical_case_id": "case::prec::123456",
                "target": "prec",
                "source_law_name": "근로기준법",
                "source_law_uid": "law-001",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "최저임금법",
                "source_file_path": "list3.json",
            }
        ],
    )
    _write_jsonl(
        root2 / "canonical_cases.jsonl",
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
                "root_law_name": "최저임금법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(detail_path2),
            }
        ],
    )

    records = build_legal_relation_records(raw_related_base_dir=raw_dir)

    # 근로기준법 시행령은 body_verified=False + search_hit only → 필터로 제거
    assert len(records) == 1

    relation_by_law = {record["law_name"]: record for record in records}

    labor_relation = relation_by_law["근로기준법"]
    assert labor_relation["id"] == "relation::case::prec::123456::law-001"
    assert labor_relation["source_hit_count"] == 2
    assert labor_relation["article_keys"] == ["43-2"]
    assert labor_relation["article_reference_sources"] == ["body_regex", "structured_field"]
    assert "cited_law" in labor_relation["relation_types"]
    assert labor_relation["relation_confidence"] == 0.98

    assert "근로기준법 시행령" not in relation_by_law


def test_build_legal_relation_records_keeps_case_reference_out_of_law_case_rows(tmp_path):
    payload = {
        "판례일련번호": "123456",
        "사건명": "임금",
        "사건번호": "2019다12345",
        "선고일자": "2019.05.30",
        "판례내용": "이 사건은 2018다12345 판결의 법리와 근로기준법 제43조의2를 함께 참조하였다.",
    }
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"
    detail_path = root / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(detail_path, payload)

    _write_jsonl(
        root / "candidate_hits.jsonl",
        [
            {
                "candidate_id": "cand1",
                "canonical_case_id": "case::prec::123456",
                "target": "prec",
                "source_law_name": "근로기준법",
                "source_law_uid": "law-001",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_file_path": "list1.json",
            }
        ],
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
                "detail_payload_path": str(detail_path),
            }
        ],
    )

    records = build_legal_relation_records(raw_related_base_dir=raw_dir)

    assert len(records) == 1
    record = records[0]
    assert record["relation_model"] == "law_to_case"
    assert "cited_case" not in record["relation_types"]
    assert "referenced_case_numbers" not in record
    assert record["relation_confidence"] == 0.95
    assert "참조 사건번호: 2018다12345" in record["text"]


def test_build_legal_relation_records_sanitizes_existing_expanded_rows(tmp_path):
    expanded_dir = tmp_path / "expanded" / "03_expanded_related_docs" / "근로기준법"
    _write_jsonl(
        expanded_dir / "relation_records.jsonl",
        [
            {
                "id": "relation::case::decc::10073::001872",
                "canonical_case_id": "case::decc::10073",
                "doc_type": "relation",
                "doc_type_label": "행정심판례",
                "source_group": "03_expanded_related_docs",
                "target": "decc",
                "title": "이행강제금 부과처분 취소청구",
                "doc_id": "10073",
                "doc_number": "2017-08376",
                "detail_link": "/DRF/lawService.do?OC=matrix2012&target=decc&ID=10073&type=HTML&mobileYn=Y",
                "law_name": "근로기준법",
                "source_law_name": "근로기준법",
                "relation_types": ["search_hit", "cited_law"],
                "text": "legacy relation",
            }
        ],
    )

    records = build_legal_relation_records(expanded_base_dir=tmp_path / "expanded" / "03_expanded_related_docs")

    assert len(records) == 1
    record = records[0]
    assert record["relation_model"] == "law_to_case"
    assert record["relation_type"] == "cited_law"
    assert record["detail_link"] == "/DRF/lawService.do?target=decc&ID=10073&type=HTML&mobileYn=Y"
    assert "OC=" not in record["text"]
    assert "OC=" not in record["display_text"]


def test_build_legal_relation_records_uses_structured_article_reference_field(tmp_path):
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"
    detail_path = root / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(
        detail_path,
        {
            "PrecService": {
                "판례정보일련번호": "123456",
                "사건명": "임금",
                "사건번호": "2019다12345",
                "선고일자": "2019.05.30",
                "참조조문": "근로기준법 제43조의2",
                "판례내용": "본문에는 조문 문자열이 직접 나오지 않는다.",
            }
        },
    )

    _write_jsonl(
        root / "candidate_hits.jsonl",
        [
            {
                "candidate_id": "cand1",
                "canonical_case_id": "case::prec::123456",
                "target": "prec",
                "source_law_name": "근로기준법",
                "source_law_uid": "law-001",
                "doc_id": "123456",
                "title": "임금",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_file_path": "list1.json",
            }
        ],
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
                "detail_payload_path": str(detail_path),
            }
        ],
    )

    records = build_legal_relation_records(raw_related_base_dir=raw_dir)

    assert len(records) == 1
    record = records[0]
    assert record["law_name"] == "근로기준법"
    assert record["article_keys"] == ["43-2"]
    assert record["article_no_displays"] == ["제43조의2"]
    assert record["article_reference_sources"] == ["structured_field"]
    assert record["relation_confidence"] == 0.98


def test_build_legal_relation_records_uses_detc_subject_article_reference_field(tmp_path):
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "파견근로자 보호 등에 관한 법률"
    detail_path = root / "canonical" / "detc" / "case_detc_17713__detail.json"
    _write_json(
        detail_path,
        {
            "DetcService": {
                "헌재결정례일련번호": "17713",
                "사건명": "구 파견근로자보호 등에 관한 법률 제45조 위헌제청",
                "사건번호": "2011헌가34",
                "종국일자": "20111124",
                "심판대상조문": (
                    "구 파견근로자 보호 등에 관한 법률(1998. 2. 20. 법률 제5512호로 "
                    "제정되고, 2006. 12. 21. 법률 제8076호로 개정되기 전의 것) "
                    "제45조"
                ),
                "전문": "본문에는 법령명이 직접 나오지 않는다.",
            }
        },
    )

    _write_jsonl(
        root / "candidate_hits.jsonl",
        [
            {
                "candidate_id": "cand1",
                "canonical_case_id": "case::detc::17713",
                "target": "detc",
                "source_law_name": "파견근로자 보호 등에 관한 법률",
                "source_law_uid": "law-001",
                "doc_id": "17713",
                "title": "구 파견근로자보호 등에 관한 법률 제45조 위헌제청",
                "doc_number": "2011헌가34",
                "root_law_name": "파견근로자 보호 등에 관한 법률",
                "source_file_path": "list1.json",
            }
        ],
    )
    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::detc::17713",
                "canonical_case_id": "case::detc::17713",
                "canonical_id": "case::detc::17713",
                "target": "detc",
                "doc_type_label": "헌재결정례",
                "doc_id": "17713",
                "title": "구 파견근로자보호 등에 관한 법률 제45조 위헌제청",
                "doc_number": "2011헌가34",
                "root_law_name": "파견근로자 보호 등에 관한 법률",
                "source_law_names": ["파견근로자 보호 등에 관한 법률"],
                "source_law_uids": ["law-001"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(detail_path),
            }
        ],
    )

    records = build_legal_relation_records(raw_related_base_dir=raw_dir)

    assert len(records) == 1
    record = records[0]
    assert record["law_name"] == "파견근로자 보호 등에 관한 법률"
    assert record["article_keys"] == []
    assert record["subject_article_keys"] == ["45"]
    assert record["subject_article_no_displays"] == ["제45조"]
    assert record["subject_article_reference_sources"] == ["structured_subject_field"]
    assert record["relation_type"] == "challenged_law"
    assert record["relation_types"] == ["search_hit", "challenged_law", "challenged_article"]
    assert record["body_verified"] is True
    assert record["relation_confidence"] == 0.99
    assert "심판대상 조문: 제45조" in record["text"]


# ── _is_unverified_search_hit 회귀 테스트 ────────────────────────────────────


def test_unverified_search_hit_law_to_case_excluded():
    """body_verified=False + ["search_hit"] law_to_case는 미검증 search_hit로 판별된다."""
    row = {
        "id": "relation::case::expc::1::law_uid_1",
        "canonical_case_id": "case::expc::1",
        "relation_model": "law_to_case",
        "body_verified": False,
        "relation_types": ["search_hit"],
        "relation_confidence": 0.45,
        "root_law_uid": "law_uid_1",
        "source_law_name": "파견근로자 보호 등에 관한 법률",
        "source_law_uid": "law_uid_1",
        "text": "폐기물처리시설 관련 해석례",
    }
    assert _is_unverified_search_hit(row) is True


def test_body_verified_cited_law_search_hit_kept():
    """body_verified=True + ["cited_law", "search_hit"] row는 미검증 아님 — 유지 대상."""
    row = {
        "relation_model": "law_to_case",
        "body_verified": True,
        "relation_types": ["cited_law", "search_hit"],
        "relation_confidence": 0.85,
    }
    assert _is_unverified_search_hit(row) is False


def test_non_law_to_case_always_kept():
    """case_to_case, law_to_law는 body_verified·relation_types 무관하게 항상 유지된다."""
    for model in ("case_to_case", "law_to_law"):
        row = {
            "relation_model": model,
            "body_verified": False,
            "relation_types": ["search_hit"],
            "relation_confidence": 0.45,
        }
        assert _is_unverified_search_hit(row) is False, f"{model} should not be flagged"


def test_build_legal_relation_records_logs_dropped_in_fallback_path(tmp_path, caplog):
    """expanded fallback 경로에서 unverified search_hit 제거 시 warning 로그가 남는다."""
    import logging

    expanded_dir = tmp_path / "expanded" / "03_expanded_related_docs" / "근로기준법"
    _write_jsonl(
        expanded_dir / "relation_records.jsonl",
        [
            {
                "id": "relation::case::prec::111::001",
                "canonical_case_id": "case::prec::111",
                "relation_model": "law_to_case",
                "relation_types": ["search_hit"],
                "body_verified": None,
                "relation_confidence": 0.45,
                "target": "prec",
                "law_name": "근로기준법",
                "source_law_name": "근로기준법",
            },
            {
                "id": "relation::case::prec::222::001",
                "canonical_case_id": "case::prec::222",
                "relation_model": "law_to_case",
                "relation_types": ["search_hit", "cited_law"],
                "body_verified": True,
                "target": "prec",
                "law_name": "근로기준법",
                "source_law_name": "근로기준법",
            },
        ],
    )

    with caplog.at_level(logging.WARNING, logger="src.export.legal_relation_builder"):
        records = build_legal_relation_records(
            expanded_base_dir=tmp_path / "expanded" / "03_expanded_related_docs"
        )

    assert len(records) == 1
    assert records[0]["canonical_case_id"] == "case::prec::222"

    drop_warnings = [m for m in caplog.messages if "dropped=" in m and "path=fallback" in m]
    assert drop_warnings, "dropped 건수 warning이 기록되어야 한다"
    assert "dropped=1" in drop_warnings[0]


def test_build_legal_relation_records_logs_warning_when_raw_has_no_data(tmp_path, caplog):
    """raw_related_base_dir을 전달했으나 데이터가 없을 때 fallback 진입 warning이 남는다."""
    import logging

    empty_raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    empty_raw_dir.mkdir(parents=True)

    with caplog.at_level(logging.WARNING, logger="src.export.legal_relation_builder"):
        build_legal_relation_records(raw_related_base_dir=empty_raw_dir)

    fallback_warnings = [m for m in caplog.messages if "raw path had no data" in m]
    assert fallback_warnings, "raw 데이터 없을 때 fallback 진입 warning이 기록되어야 한다"
