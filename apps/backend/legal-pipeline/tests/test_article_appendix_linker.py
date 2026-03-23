from __future__ import annotations

import json

from src.common.io_utils import _write_json
from src.export.article_appendix_linker import (
    build_article_appendix_links,
    augment_law_records_with_appendices,
    extract_article_keys,
)
from src.export.dataset_builder import build_and_write_datasets


def test_extract_article_keys_handles_branch_articles():
    assert extract_article_keys("임신 중인 여성의 사용 금지 직종(제11조의2 관련)") == ["11-2"]
    assert extract_article_keys("제4조 및 제5조 관련") == ["4", "5"]


def test_build_article_appendix_links_and_augment_rows(tmp_path):
    law_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"
    appendix_dir = tmp_path / "normalized" / "01_current_law_appendix" / "근로기준법"

    _write_json(
        law_dir / "근로기준법_시행규칙__parsed_law.json",
        {
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
            "kind_name": "고용노동부령",
            "classified_level": "시행규칙",
            "articles": [
                {
                    "article_no": "제4조",
                    "article_no_display": "제4조",
                    "article_key": "4",
                    "article_title": "해고 예고의 예외",
                    "article_text_raw": "제4조(해고 예고의 예외) 해고 예고의 예외가 되는 근로자의 귀책사유는 별표 1과 같다.",
                    "article_text": "제4조(해고 예고의 예외) 해고 예고의 예외가 되는 근로자의 귀책사유는 별표 1과 같다.",
                    "paragraphs": [],
                },
                {
                    "article_no": "제5조",
                    "article_no_display": "제5조",
                    "article_key": "5",
                    "article_title": "그 밖의 사항",
                    "article_text_raw": "제5조(그 밖의 사항) 기타 사항을 정한다.",
                    "article_text": "제5조(그 밖의 사항) 기타 사항을 정한다.",
                    "paragraphs": [],
                },
            ],
            "supplementary": [],
            "appendices": [],
        },
    )

    _write_json(
        appendix_dir / "근로기준법_시행규칙__parsed_appendix.json",
        {
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
            "appendix_records": [
                {
                    "id": "appendix::근로기준법_시행규칙::000100E",
                    "law_name": "근로기준법 시행규칙",
                    "law_id": "006859",
                    "mst": "269393",
                    "kind_name": "고용노동부령",
                    "appendix_key": "000100E",
                    "appendix_no": "0001",
                    "appendix_kind": "별표",
                    "appendix_type": "appendix_document",
                    "appendix_title_raw": "해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)",
                    "appendix_title": "해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)",
                    "api_document_markdown": "# 해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)\n\n## 1. 납품업체로부터 금품이나 향응을 제공받은 경우",
                    "api_table_count": 2,
                }
            ],
        },
    )

    result = build_article_appendix_links(
        normalized_base_dir=tmp_path / "normalized" / "01_current_law",
        normalized_appendix_base_dir=tmp_path / "normalized" / "01_current_law_appendix",
    )

    assert result["manifest"]["appendix_bundle_count"] == 1
    assert result["manifest"]["article_with_appendix_count"] == 1
    assert result["manifest"]["article_appendix_link_count"] == 1

    law_records = [
        {
            "id": "law::006859::article::4::0",
            "text": "법령명: 근로기준법 시행규칙\n조문번호: 제4조\n제4조(해고 예고의 예외) 해고 예고의 예외가 되는 근로자의 귀책사유는 별표 1과 같다.",
            "doc_type": "law",
            "section_type": "article",
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
            "article_key": "4",
            "article_no": "4",
            "article_no_display": "제4조",
            "chunk_index": 0,
        },
        {
            "id": "law::006859::article::5::0",
            "text": "법령명: 근로기준법 시행규칙\n조문번호: 제5조\n제5조(그 밖의 사항) 기타 사항을 정한다.",
            "doc_type": "law",
            "section_type": "article",
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
            "article_key": "5",
            "article_no": "5",
            "article_no_display": "제5조",
            "chunk_index": 0,
        },
    ]

    augmented = augment_law_records_with_appendices(law_records, article_links=result["article_links"])
    linked, unlinked = augmented

    assert linked["has_related_appendix"] is True
    assert linked["related_appendix_count"] == 1
    assert linked["related_appendix_titles"] == ["해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)"]
    assert "## 1. 납품업체로부터 금품이나 향응을 제공받은 경우" in linked["appendix_vector_text"]
    assert linked["related_appendices"][0]["match_types"] == ["appendix_title_reference", "law_body_reverse_match"]
    assert unlinked["has_related_appendix"] is False
    assert unlinked["appendix_vector_text"] == "[NO_APPENDIX_LINKED]"


def test_build_and_write_datasets_merges_appendices_into_law_article(tmp_path):
    law_dir = tmp_path / "normalized" / "01_current_law" / "근로기준법"
    appendix_dir = tmp_path / "normalized" / "01_current_law_appendix" / "근로기준법"
    dataset_dir = tmp_path / "dataset"

    _write_json(
        law_dir / "근로기준법_시행규칙__parsed_law.json",
        {
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
            "kind_name": "고용노동부령",
            "classified_level": "시행규칙",
            "articles": [
                {
                    "article_no": "제4조",
                    "article_no_display": "제4조",
                    "article_key": "4",
                    "article_title_raw": "해고 예고의 예외",
                    "article_title": "해고 예고의 예외",
                    "article_text_raw": "제4조(해고 예고의 예외) 해고 예고의 예외가 되는 근로자의 귀책사유는 별표 1과 같다.",
                    "article_text": "제4조(해고 예고의 예외) 해고 예고의 예외가 되는 근로자의 귀책사유는 별표 1과 같다.",
                    "paragraphs": [],
                }
            ],
            "supplementary": [],
            "appendices": [],
        },
    )

    _write_json(
        appendix_dir / "근로기준법_시행규칙__parsed_appendix.json",
        {
            "law_name": "근로기준법 시행규칙",
            "law_id": "006859",
            "mst": "269393",
            "appendix_records": [
                {
                    "id": "appendix::근로기준법_시행규칙::000100E",
                    "law_name": "근로기준법 시행규칙",
                    "law_id": "006859",
                    "mst": "269393",
                    "kind_name": "고용노동부령",
                    "appendix_key": "000100E",
                    "appendix_no": "0001",
                    "appendix_kind": "별표",
                    "appendix_type": "appendix_document",
                    "appendix_title_raw": "해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)",
                    "appendix_title": "해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)",
                    "api_document_markdown": "# 해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)\n\n## 1. 납품업체로부터 금품이나 향응을 제공받은 경우",
                    "api_table_count": 0,
                }
            ],
        },
    )

    manifest = build_and_write_datasets(
        normalized_base_dir=tmp_path / "normalized" / "01_current_law",
        raw_related_base_dir=tmp_path / "raw" / "02_related_legal_docs",
        expanded_base_dir=tmp_path / "expanded" / "03_expanded_related_docs",
        output_dir=dataset_dir,
        normalized_appendix_base_dir=tmp_path / "normalized" / "01_current_law_appendix",
        merge_appendices_into_law_article=True,
        include_appendix_bundle_text_in_payload=True,
        write_legacy_appendix_datasets=False,
    )

    corpus_rows = [json.loads(line) for line in (dataset_dir / "legal_corpus.jsonl").open(encoding="utf-8")]
    assert len(corpus_rows) == 1
    row = corpus_rows[0]
    assert row["has_related_appendix"] is True
    assert row["related_appendix_count"] == 1
    assert row["related_appendix_titles"] == ["해고 예고의 예외가 되는 근로자의 귀책사유(제4조 관련)"]
    assert "## 1. 납품업체로부터 금품이나 향응을 제공받은 경우" in row["appendix_vector_text"]
    assert manifest["article_appendix_manifest"]["article_appendix_link_count"] == 1
    assert (dataset_dir / "article_appendix_links.jsonl").exists()
    assert (dataset_dir / "appendix_bundle_records.jsonl").exists()
