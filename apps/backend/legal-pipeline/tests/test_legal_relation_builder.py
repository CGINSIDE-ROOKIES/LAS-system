import json
from pathlib import Path

from src.common.io_utils import _write_json, _write_jsonl
from src.export.legal_relation_builder import build_legal_relation_records


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

    assert len(records) == 2

    relation_by_law = {record["law_name"]: record for record in records}

    labor_relation = relation_by_law["근로기준법"]
    assert labor_relation["id"] == "relation::case::prec::123456::law-001"
    assert labor_relation["source_hit_count"] == 2
    assert labor_relation["article_keys"] == ["43-2"]
    assert "cited_law" in labor_relation["relation_types"]
    assert labor_relation["relation_confidence"] == 0.95

    decree_relation = relation_by_law["근로기준법 시행령"]
    assert decree_relation["source_hit_count"] == 1
    assert decree_relation["article_keys"] == []
    assert decree_relation["relation_types"] == ["search_hit"]


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
    assert "관련 조문: 제43조의2" in record["text"]


def test_build_legal_relation_records_does_not_treat_amount_text_as_cited_case(tmp_path):
    payload = {
        "판례일련번호": "123456",
        "사건명": "임금",
        "사건번호": "2019다12345",
        "선고일자": "2019.05.30",
        "판례내용": "피고는 근로기준법 제43조의2에 따라 119만2666원과 66만4000원을 지급하여야 한다.",
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
    assert "cited_case" not in record["relation_types"]
    assert "referenced_case_numbers" not in record


def test_build_legal_relation_records_keeps_all_article_refs_in_single_relation(tmp_path):
    payload = {
        "판례일련번호": "123456",
        "사건명": "임금",
        "사건번호": "2019다12345",
        "선고일자": "2019.05.30",
        "판례내용": "이 사건은 근로기준법 제23조, 30조 및 제43조의2를 함께 참조하였다.",
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
    assert record["article_keys"] == ["23", "30", "43-2"]
    assert record["article_no_displays"] == ["제23조", "제30조", "제43조의2"]
    assert "관련 조문: 제23조, 제30조, 제43조의2" in record["text"]
