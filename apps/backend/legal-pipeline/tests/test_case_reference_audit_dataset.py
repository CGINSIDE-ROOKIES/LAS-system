from src.common.io_utils import _iter_jsonl, _write_json
from src.export.dataset_builder import build_and_write_datasets


def test_build_and_write_datasets_writes_case_reference_audit_and_manifest(tmp_path):
    normalized_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"
    parsed_law_path = normalized_dir / "근로기준법__parsed_law.json"
    _write_json(
        parsed_law_path,
        {
            "law_name": "근로기준법",
            "law_id": "001",
            "mst": "mst001",
            "ef_yd": "20240101",
            "kind_name": "법률",
            "articles": [
                {
                    "article_no": "43",
                    "article_no_display": "제43조의2",
                    "article_no_main": "43",
                    "article_no_branch": "2",
                    "article_key": "43-2",
                    "article_title_raw": "체불사업주 명단 공개",
                    "article_title": "체불사업주 명단 공개",
                    "article_text_raw": "제43조의2(체불사업주 명단 공개) 본문",
                    "article_text": "제43조의2(체불사업주 명단 공개) 본문",
                    "paragraphs": [],
                }
            ],
            "supplementary": [],
            "appendices": [],
        },
    )

    raw_dir = tmp_path / "raw" / "02_related_legal_docs" / "근로기준법"
    source_detail_path = raw_dir / "canonical" / "prec" / "case_prec_123456__detail.json"
    _write_json(
        source_detail_path,
        {
            "판례일련번호": "123456",
            "사건명": "임금",
            "사건번호": "2019다12345",
            "선고일자": "2019.05.30",
            "판례내용": "이 사건은 2027다99999 판결과 근로기준법 제43조의2를 함께 참조하였다.",
        },
    )
    canonical_path = raw_dir / "canonical_cases.jsonl"
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(
        "\n".join(
            [
                '{"id":"case::prec::123456","canonical_case_id":"case::prec::123456","canonical_id":"case::prec::123456","target":"prec","doc_type_label":"판례","doc_id":"123456","title":"임금","doc_number":"2019다12345","root_law_name":"근로기준법","source_law_names":["근로기준법"],"source_law_uids":["law-001"],"source_hit_count":1,"detail_available":true,"detail_payload_path":"'
                + str(source_detail_path)
                + '"}'
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    candidate_path = raw_dir / "candidate_hits.jsonl"
    candidate_path.write_text(
        "\n".join(
            [
                '{"candidate_id":"cand1","canonical_case_id":"case::prec::123456","target":"prec","source_law_name":"근로기준법","source_law_uid":"law-001","doc_id":"123456","title":"임금","doc_number":"2019다12345","root_law_name":"근로기준법","source_file_path":"list1.json"}'
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = build_and_write_datasets(
        normalized_base_dir=tmp_path / "normalized" / "01_current_law",
        raw_related_base_dir=tmp_path / "raw" / "02_related_legal_docs",
        expanded_base_dir=tmp_path / "expanded" / "03_expanded_related_docs",
        output_dir=tmp_path / "dataset",
        merge_appendices_into_law_article=False,
        write_legacy_appendix_datasets=False,
    )

    audit_rows = list(_iter_jsonl(tmp_path / "dataset" / "case_reference_audit.jsonl"))

    assert len(audit_rows) == 1
    assert audit_rows[0]["resolution_status"] == "unresolved_external"
    assert manifest["case_reference_audit_manifest"]["audit_record_count"] == 1
    assert manifest["case_reference_audit_manifest"]["unresolved_external_count"] == 1
