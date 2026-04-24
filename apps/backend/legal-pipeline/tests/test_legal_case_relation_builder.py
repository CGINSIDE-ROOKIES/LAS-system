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
            "참조판례": "대법원 2018. 4. 20. 선고 2018다12345 판결",
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
    assert "structured_field" in record["reference_sources"]
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
    assert by_ref["2018다12345"]["reference_sources"] == ["body_regex"]
    assert by_ref["2027다99999"]["resolution_status"] == "unresolved_external"
    assert by_ref["2027다99999"]["candidate_count"] == 0
    # 기본값(True)이면 모든 row에 audit_includes_body_regex=True 기록
    assert all(r["audit_includes_body_regex"] is True for r in records)


def test_build_case_reference_audit_records_structured_only(tmp_path):
    """include_body_regex=False: body_text 기반 참조는 제외, export graph와 동일 기준."""
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
            # 구조화 참조 없음 — body text에만 사건번호 존재
            "판례내용": "이 사건은 2018다12345 판결을 참조하였다.",
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
                "doc_id": "123456",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "detail_available": True,
                "detail_payload_path": str(source_detail_path),
            },
            {
                "id": "case::prec::777777",
                "canonical_case_id": "case::prec::777777",
                "canonical_id": "case::prec::777777",
                "target": "prec",
                "doc_id": "777777",
                "doc_number": "2018다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "detail_available": False,
                "detail_payload_path": None,
            },
        ],
    )

    # structured_only: body_regex 참조 제외 → 결과 0건
    records_structured = build_case_reference_audit_records(
        raw_related_base_dir=raw_dir, include_body_regex=False
    )
    assert records_structured == []

    # body_regex 포함(기본): 결과 1건
    records_full = build_case_reference_audit_records(
        raw_related_base_dir=raw_dir, include_body_regex=True
    )
    assert len(records_full) == 1
    assert records_full[0]["reference_sources"] == ["body_regex"]
    assert records_full[0]["audit_includes_body_regex"] is True


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
    assert records[0]["reference_sources"] == ["structured_field"]


def test_build_case_to_case_relation_records_logs_expc_mapping_stats(tmp_path, caplog):
    """expc→prec 매핑 결과(success/no_candidate/ambiguous)가 info 로그로 기록된다."""
    import json
    import logging

    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"

    # expc canonical row
    expc_cid = "case::expc::9001"
    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": expc_cid,
                "canonical_case_id": expc_cid,
                "canonical_id": expc_cid,
                "target": "expc",
                "doc_id": "9001",
                "doc_number": "21-0001",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "detail_available": False,
                "detail_payload_path": None,
            },
            {
                "id": "case::prec::111",
                "canonical_case_id": "case::prec::111",
                "canonical_id": "case::prec::111",
                "target": "prec",
                "doc_id": "111",
                "doc_number": "2018다111",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "detail_available": False,
                "detail_payload_path": None,
            },
        ],
    )

    # sidecar: prec_id=111 (success) + prec_id=999 (no_candidate)
    sidecar_path = root / "canonical" / "expc" / f"{expc_cid.replace('::', '__')}__related_prec_ids.json"
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps({"related_prec_ids": ["111", "999"]}), encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="src.export.legal_case_relation_builder"):
        records = build_case_to_case_relation_records(raw_related_base_dir=raw_dir)

    assert len(records) == 1
    assert records[0]["source_case_type"] == "expc"

    stat_logs = [m for m in caplog.messages if "expc->prec mapping stats" in m]
    assert stat_logs, "mapping stats info 로그가 기록되어야 한다"
    assert "success" in stat_logs[0]
    assert "no_candidate" in stat_logs[0]


def test_build_case_to_case_relation_records_sets_root_law_uid(tmp_path):
    """case_to_case 레코드에 root_law_uid가 null 없이 설정된다 (이슈 F)."""
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"

    source_detail_path = root / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(
        source_detail_path,
        {
            "판례일련번호": "123456",
            "사건번호": "2019다12345",
            "선고일자": "2019.05.30",
            "참조판례": "대법원 2018. 4. 20. 선고 2018다12345 판결",
            "판례내용": "이 사건은 근로기준법 제43조를 적용하여 2018다12345 판결의 법리를 따랐다.",
        },
    )
    target_detail_path = root / "canonical" / "prec" / "case_prec_777777__detail.json"
    _write_json(
        target_detail_path,
        {"판례일련번호": "777777", "사건번호": "2018다12345", "판례내용": "선행 판결"},
    )

    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::prec::123456",
                "canonical_case_id": "case::prec::123456",
                "canonical_id": "case::prec::123456",
                "target": "prec",
                "doc_id": "123456",
                "doc_number": "2019다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "detail_available": True,
                "detail_payload_path": str(source_detail_path),
            },
            {
                "id": "case::prec::777777",
                "canonical_case_id": "case::prec::777777",
                "canonical_id": "case::prec::777777",
                "target": "prec",
                "doc_id": "777777",
                "doc_number": "2018다12345",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["law-001"],
                "detail_available": True,
                "detail_payload_path": str(target_detail_path),
            },
        ],
    )

    records = build_case_to_case_relation_records(raw_related_base_dir=raw_dir)

    assert len(records) == 1
    record = records[0]
    assert record["root_law_name"] == "근로기준법"
    assert record["root_law_uid"] is not None, "root_law_uid가 null이면 Neo4j 그래프 edge 누락 발생"
    assert "근로기준법" in record["root_law_uid"]


def test_build_case_to_case_relation_records_deduplicates_bidirectional(tmp_path):
    """이슈 N: A→B와 B→A가 동시에 생성될 때 하나만 유지된다."""
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "근로기준법"

    # source A references B via structured field
    detail_a = root / "canonical" / "prec" / "case_prec_AAA__detail.json"
    _write_json(
        detail_a,
        {
            "판례일련번호": "AAA",
            "사건번호": "2019다111",
            "참조판례": "대법원 2018. 1. 1. 선고 2018다222 판결",
            "판례내용": "선행 2018다222 판결 참조.",
        },
    )
    # source B references A via structured field (creates reverse edge)
    detail_b = root / "canonical" / "prec" / "case_prec_BBB__detail.json"
    _write_json(
        detail_b,
        {
            "판례일련번호": "BBB",
            "사건번호": "2018다222",
            "참조판례": "대법원 2019. 5. 1. 선고 2019다111 판결",
            "판례내용": "후속 2019다111 판결을 인용.",
        },
    )

    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::prec::AAA",
                "canonical_case_id": "case::prec::AAA",
                "canonical_id": "case::prec::AAA",
                "target": "prec",
                "doc_id": "AAA",
                "doc_number": "2019다111",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "detail_available": True,
                "detail_payload_path": str(detail_a),
            },
            {
                "id": "case::prec::BBB",
                "canonical_case_id": "case::prec::BBB",
                "canonical_id": "case::prec::BBB",
                "target": "prec",
                "doc_id": "BBB",
                "doc_number": "2018da222",
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "detail_available": True,
                "detail_payload_path": str(detail_b),
            },
        ],
    )

    records = build_case_to_case_relation_records(raw_related_base_dir=raw_dir)

    # 양방향이 생성됐더라도 최종 결과는 1건이어야 함
    pairs = {
        (r["source_canonical_case_id"], r["target_canonical_case_id"])
        for r in records
    }
    # 정방향, 역방향이 동시에 존재해서는 안 됨
    for src, tgt in list(pairs):
        assert (tgt, src) not in pairs, "양방향 중복 레코드가 dedup 없이 포함됨"
