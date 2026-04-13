from src.export.legal_case_dataset_builder import (
    CHUNKING_CONFIG,
    FIELD_GROUPS,
    _build_case_blocks,
    build_legal_case_records,
)
from src.common.io_utils import _write_json, _write_jsonl


# ---------------------------------------------------------------------------
# _build_case_blocks 단위 테스트
# ---------------------------------------------------------------------------


def _make_parsed(target: str, sections: list[dict]) -> dict:
    return {
        "target": target,
        "title": "테스트 제목",
        "doc_number": "2023다12345",
        "decision_date": "2023.01.01",
        "body_text": " ".join(s.get("text", "") for s in sections),
        "body_sections": sections,
        "body_type": "text",
    }


def _make_row(target: str) -> dict:
    return {"target": target, "source_law_names": ["테스트법"]}


def test_build_case_blocks_prec_header_in_first_block():
    sections = [
        {"label": "판시사항", "text": "판시사항 내용"},
        {"label": "판결요지", "text": "판결요지 내용"},
        {"label": "참조조문", "text": "참조조문 내용"},
        {"label": "참조판례", "text": "참조판례 내용"},
        {"label": "판례내용", "text": "판례내용 본문 " * 100},
    ]
    parsed = _make_parsed("prec", sections)
    row = _make_row("prec")

    blocks = _build_case_blocks(parsed, row)

    # 첫 블록에 preamble + header 필드 포함
    assert len(blocks) >= 2
    first = blocks[0]
    assert "판시사항 내용" in first
    assert "판결요지 내용" in first
    assert "참조조문 내용" in first
    assert "참조판례 내용" in first
    assert "테스트 제목" in first  # preamble 포함

    # 판례내용은 별도 블록
    body_text = "\n\n".join(blocks[1:])
    assert "판례내용 본문" in body_text
    assert "판례내용 본문" not in first


def test_build_case_blocks_detc_body_is_separate():
    sections = [
        {"label": "판시사항", "text": "판시사항"},
        {"label": "결정요지", "text": "결정요지"},
        {"label": "심판대상조문", "text": "심판대상조문"},
        {"label": "전문", "text": "전문 내용 " * 200},
    ]
    parsed = _make_parsed("detc", sections)
    row = _make_row("detc")

    blocks = _build_case_blocks(parsed, row)

    assert len(blocks) >= 2
    first = blocks[0]
    assert "판시사항" in first
    assert "결정요지" in first
    assert "심판대상조문" in first

    # 전문은 별도 블록
    assert "전문 내용" not in first
    assert any("전문 내용" in b for b in blocks[1:])


def test_build_case_blocks_expc_header_in_first_block():
    sections = [
        {"label": "질의요지", "text": "질의요지 내용"},
        {"label": "회답", "text": "회답 내용"},
        {"label": "이유", "text": "이유 내용 " * 100},
    ]
    parsed = _make_parsed("expc", sections)
    row = _make_row("expc")

    blocks = _build_case_blocks(parsed, row)

    assert len(blocks) >= 2
    first = blocks[0]
    assert "질의요지 내용" in first
    assert "회답 내용" in first
    assert "이유 내용" not in first

    assert any("이유 내용" in b for b in blocks[1:])


def test_build_case_blocks_decc_header_in_first_block():
    sections = [
        {"label": "청구취지", "text": "청구취지 내용"},
        {"label": "주문", "text": "주문 내용"},
        {"label": "재결요지", "text": "재결요지 내용"},
        {"label": "이유", "text": "이유 내용 " * 100},
    ]
    parsed = _make_parsed("decc", sections)
    row = _make_row("decc")

    blocks = _build_case_blocks(parsed, row)

    assert len(blocks) >= 2
    first = blocks[0]
    assert "청구취지 내용" in first
    assert "주문 내용" in first
    assert "재결요지 내용" in first
    assert "이유 내용" not in first


def test_build_case_blocks_unknown_target_fallback():
    """알 수 없는 target은 기존 방식(개별 블록)으로 처리."""
    sections = [
        {"label": "섹션A", "text": "내용A"},
        {"label": "섹션B", "text": "내용B"},
    ]
    parsed = _make_parsed("unknown_type", sections)
    row = _make_row("unknown_type")

    blocks = _build_case_blocks(parsed, row)

    # preamble + 각 섹션 개별 블록
    assert len(blocks) == 3
    assert any("내용A" in b for b in blocks)
    assert any("내용B" in b for b in blocks)
    # 서로 다른 블록에 분리
    first_with_a = next(i for i, b in enumerate(blocks) if "내용A" in b)
    first_with_b = next(i for i, b in enumerate(blocks) if "내용B" in b)
    assert first_with_a != first_with_b


def test_build_case_blocks_extra_sections_before_body():
    """미분류 섹션은 body(장문 본문) 앞에 배치된다."""
    sections = [
        {"label": "질의요지", "text": "질의요지 내용"},
        {"label": "회답", "text": "회답 내용"},
        {"label": "미분류섹션", "text": "미분류 내용"},
        {"label": "이유", "text": "이유 본문 " * 50},
    ]
    parsed = _make_parsed("expc", sections)
    row = _make_row("expc")

    blocks = _build_case_blocks(parsed, row)

    assert len(blocks) == 3  # [header, extra, body]
    assert "미분류 내용" in blocks[1]
    assert "이유 본문" in blocks[2]


def test_build_case_blocks_first_block_splits_when_too_long(tmp_path):
    """첫 블록(header)이 max_chars를 초과하면 overlap=0으로 분할되고 첫 조각이 chunk 0이 된다."""
    from src.common.io_utils import _write_json, _write_jsonl
    from src.export.legal_case_dataset_builder import build_legal_case_records, CHUNKING_CONFIG

    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "테스트법"

    max_chars = CHUNKING_CONFIG["prec"]["max_chars"]  # 1400
    # header 섹션 4개를 각각 400자로 만들면 합산 > 1400
    long_header = "가" * 400

    detail_path = root / "canonical" / "prec" / "case_prec_999__detail.json"
    _write_json(
        detail_path,
        {
            "판례": {
                "판례정보일련번호": "999",
                "사건명": "헤더초과 테스트",
                "사건번호": "2023다9999",
                "선고일자": "2023.01.01",
                "판시사항": long_header,
                "판결요지": long_header,
                "참조조문": long_header,
                "참조판례": long_header,
                "판례내용": "판례내용 본문",
            }
        },
    )
    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::prec::999",
                "canonical_case_id": "case::prec::999",
                "canonical_id": "case::prec::999",
                "target": "prec",
                "doc_type_label": "판례",
                "doc_id": "999",
                "title": "헤더초과 테스트",
                "doc_number": "2023다9999",
                "root_law_name": "테스트법",
                "source_law_names": ["테스트법"],
                "source_law_uids": ["law-test"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(detail_path),
            }
        ],
    )

    records = build_legal_case_records(raw_related_base_dir=raw_dir)

    assert len(records) >= 2, "첫 블록이 max_chars 초과 시 분할되어야 함"
    # 각 chunk가 max_chars의 10% 여유 범위 이내여야 함
    for r in records:
        assert len(r["text"]) <= max_chars * 1.1
    # chunk_index가 순서대로 증가해야 함
    chunk_indices = [r["chunk_index"] for r in records]
    assert chunk_indices == list(range(len(records)))


def test_build_case_blocks_detc_no_header_preamble_merged():
    """detc에서 header 섹션 없이 전문만 있으면 preamble이 전문 블록 앞에 합쳐짐."""
    sections = [{"label": "전문", "text": "전문 내용 " * 50}]
    parsed = _make_parsed("detc", sections)
    row = _make_row("detc")

    blocks = _build_case_blocks(parsed, row)

    assert len(blocks) == 1
    assert "테스트 제목" in blocks[0]  # preamble 포함
    assert "전문 내용" in blocks[0]    # 전문 포함


def test_build_case_blocks_prec_no_header_preamble_merged():
    """prec에서 header 섹션 없이 판례내용만 있으면 preamble이 판례내용 블록 앞에 합쳐짐."""
    sections = [{"label": "판례내용", "text": "판례내용 본문 " * 50}]
    parsed = _make_parsed("prec", sections)
    row = _make_row("prec")

    blocks = _build_case_blocks(parsed, row)

    assert len(blocks) == 1
    assert "테스트 제목" in blocks[0]
    assert "판례내용 본문" in blocks[0]


def test_build_case_blocks_no_header_extra_block_merged_with_preamble():
    """header도 body도 아닌 extra 섹션만 있을 때 preamble이 extra 앞에 합쳐짐."""
    sections = [{"label": "미분류섹션", "text": "미분류 내용"}]
    parsed = _make_parsed("prec", sections)
    row = _make_row("prec")

    blocks = _build_case_blocks(parsed, row)

    assert len(blocks) == 1
    assert "테스트 제목" in blocks[0]  # preamble
    assert "미분류 내용" in blocks[0]  # extra


def test_build_case_blocks_no_sections_fallback():
    """body_sections가 없으면 full_text fallback."""
    parsed = {
        "target": "prec",
        "title": "제목",
        "doc_number": "2023다1",
        "decision_date": "2023.01.01",
        "body_text": "본문 내용",
        "body_sections": [],
        "body_type": "text",
    }
    row = _make_row("prec")

    blocks = _build_case_blocks(parsed, row)

    assert len(blocks) >= 1
    combined = "\n\n".join(blocks)
    assert "본문 내용" in combined


# ---------------------------------------------------------------------------
# build_legal_case_records per-type 청킹 통합 테스트
# ---------------------------------------------------------------------------


def test_build_legal_case_records_uses_per_type_chunking(tmp_path):
    """detc는 max_chars=1600으로, expc는 max_chars=1100으로 청킹됨을 확인."""
    raw_dir = tmp_path / "raw" / "02_related_legal_docs"
    root = raw_dir / "테스트법"

    long_text = "가나다라마바사아자차카타파하 " * 120  # ~2400자

    detc_detail = root / "canonical" / "detc" / "case_detc_111__detail.json"
    _write_json(
        detc_detail,
        {
            "판례": {
                "판례정보일련번호": "111",
                "사건명": "detc 테스트",
                "사건번호": "2023헌마1",
                "종국일자": "2023.01.01",
                "전문": long_text,
            }
        },
    )

    expc_detail = root / "canonical" / "expc" / "case_expc_222__detail.json"
    _write_json(
        expc_detail,
        {
            "법령해석": {
                "법령해석례일련번호": "222",
                "제목": "expc 테스트",
                "문서번호": "23-001",
                "회신일자": "2023.01.01",
                "이유": long_text,
            }
        },
    )

    _write_jsonl(
        root / "canonical_cases.jsonl",
        [
            {
                "id": "case::detc::111",
                "canonical_case_id": "case::detc::111",
                "canonical_id": "case::detc::111",
                "target": "detc",
                "doc_type_label": "헌재결정례",
                "doc_id": "111",
                "title": "detc 테스트",
                "doc_number": "2023헌마1",
                "root_law_name": "테스트법",
                "source_law_names": ["테스트법"],
                "source_law_uids": ["law-test"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(detc_detail),
            },
            {
                "id": "case::expc::222",
                "canonical_case_id": "case::expc::222",
                "canonical_id": "case::expc::222",
                "target": "expc",
                "doc_type_label": "법령해석례",
                "doc_id": "222",
                "title": "expc 테스트",
                "doc_number": "23-001",
                "root_law_name": "테스트법",
                "source_law_names": ["테스트법"],
                "source_law_uids": ["law-test"],
                "source_hit_count": 1,
                "detail_available": True,
                "detail_payload_path": str(expc_detail),
            },
        ],
    )

    records = build_legal_case_records(raw_related_base_dir=raw_dir)

    detc_chunks = [r for r in records if r["doc_type"] == "detc"]
    expc_chunks = [r for r in records if r["doc_type"] == "expc"]

    assert detc_chunks, "detc 레코드가 생성되어야 함"
    assert expc_chunks, "expc 레코드가 생성되어야 함"

    # detc max_chars=1600 > expc max_chars=1100 이므로 detc가 fewer chunks
    # (동일 텍스트 기준, 더 큰 max_chars → chunk 수 적음)
    assert len(detc_chunks) <= len(expc_chunks), (
        f"detc(max_chars=1600)는 expc(max_chars=1100)보다 chunk 수가 같거나 적어야 함: "
        f"detc={len(detc_chunks)}, expc={len(expc_chunks)}"
    )

    # 각 chunk가 해당 유형의 max_chars를 초과하지 않는지 확인 (overlap 때문에 약간 초과 가능)
    detc_cfg = CHUNKING_CONFIG["detc"]
    expc_cfg = CHUNKING_CONFIG["expc"]
    for r in detc_chunks:
        assert len(r["text"]) <= detc_cfg["max_chars"] * 1.1
    for r in expc_chunks:
        assert len(r["text"]) <= expc_cfg["max_chars"] * 1.1
