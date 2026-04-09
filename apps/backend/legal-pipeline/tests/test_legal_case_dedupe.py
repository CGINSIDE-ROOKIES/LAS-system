import json
from pathlib import Path

from src.common.io_utils import _write_json, _write_jsonl
from src.export.legal_case_dataset_builder import build_legal_case_records


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "legal_case"



def test_build_legal_case_records_dedupes_canonical_case_across_roots(tmp_path):
    payload = json.loads((FIXTURE_DIR / "prec_detail.json").read_text(encoding="utf-8"))
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"

    for root_name, source_law_name in [("근로기준법", "근로기준법"), ("최저임금법", "최저임금법")]:
        root_dir = raw_dir / root_name
        detail_path = root_dir / "canonical" / "prec" / "case_prec_123456__detail.json"
        _write_json(detail_path, payload)
        _write_jsonl(
            root_dir / "canonical_cases.jsonl",
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
                    "root_law_name": root_name,
                    "source_law_names": [source_law_name],
                    "source_law_uids": [source_law_name],
                    "source_hit_count": 1,
                    "detail_available": True,
                    "detail_payload_path": str(detail_path),
                }
            ],
        )

    records = build_legal_case_records(raw_related_base_dir=raw_dir)

    # canonical_case_id가 하나만 존재하는지 (중복 제거 검증)
    unique_case_ids = {r["canonical_case_id"] for r in records}
    assert unique_case_ids == {"case::prec::123456"}
    # 관련 법령이 두 법령 모두 포함되어야 함 (병합 검증)
    assert records[0]["related_law_names"] == ["근로기준법", "최저임금법"]
    # chunk_index가 0부터 시작해야 함
    assert records[0]["id"] == "case_chunk::case::prec::123456::0"


def test_build_legal_case_records_preserves_section_headers_in_chunks(tmp_path):
    payload = json.loads((FIXTURE_DIR / "expc_detail.json").read_text(encoding="utf-8"))
    payload["ExpcService"]["질의요지"] = "질의요지 " + ("A" * 240)
    payload["ExpcService"]["회답"] = "회답 " + ("B" * 220)
    payload["ExpcService"]["이유"] = "이유 " + ("C" * 260)

    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root_dir = raw_dir / "근로기준법"
    detail_path = root_dir / "canonical" / "expc" / "case_expc_330471__detail.json"
    _write_json(detail_path, payload)
    _write_jsonl(
        root_dir / "canonical_cases.jsonl",
        [
            {
                "id": "case::expc::330471",
                "canonical_case_id": "case::expc::330471",
                "canonical_id": "case::expc::330471",
                "target": "expc",
                "doc_type_label": "법령해석례",
                "doc_id": "330471",
                "title": payload["ExpcService"]["안건명"],
                "doc_number": payload["ExpcService"]["안건번호"],
                "root_law_name": "근로기준법",
                "source_law_names": ["근로기준법"],
                "source_law_uids": ["근로기준법"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(detail_path),
            }
        ],
    )

    records = build_legal_case_records(raw_related_base_dir=raw_dir)

    # 새 필드 보존형 청킹: header(질의요지+회답)는 첫 청크, body(이유)는 별도 청크
    assert len(records) >= 2
    assert "질의요지" in records[0]["text"]
    assert "회답" in records[0]["text"]
    assert any("이유" in r["text"] for r in records)
