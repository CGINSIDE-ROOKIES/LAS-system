from __future__ import annotations

import json
import unittest

from doc_processor.contract_review import ContractReviewConfig, review_parsed_contract
from doc_processor.api_types import ClauseSummary, ParagraphPreview, ParseDocumentResult


class FakeRagClient:
    def __init__(self) -> None:
        self.queries: list[dict[str, object]] = []

    def query_legal_db(self, query: str, **kwargs):
        self.queries.append({"query": query, **kwargs})
        return {
            "documents": [
                {
                    "rank": 1,
                    "source_id": "law-1",
                    "doc_type": "law",
                    "law_name": "근로기준법",
                    "article_no": "제20조",
                    "citation": "근로기준법 제20조 (law-1)",
                    "snippet": "위약 예정 금지",
                    "text": "근로계약 불이행에 대한 위약금 또는 손해배상액을 예정하지 못한다.",
                    "score": 0.91,
                }
            ],
            "law_context_status": "ok",
        }


class FakeGenerationClient:
    def generate(self, prompt: str, *, system_prompt: str | None = None):
        return type(
            "Generation",
            (),
            {
                "answer": json.dumps(
                    {
                        "findings": [
                            {
                                "severity": "high",
                                "issue_type": "penalty_clause",
                                "title": "위약금 예정 조항",
                                "target_node_id": "p1",
                                "selected_text": "위약금 1,000만원을 지급한다",
                                "rationale": "검색 근거는 근로계약 불이행 위약 예정 금지를 설명한다.",
                                "recommendation": "위약금 예정 표현을 삭제하고 실제 손해 입증 기준으로 바꾼다.",
                                "replacement_text": "실제 발생한 손해에 한해 관련 법령에 따라 배상한다",
                                "source_ids": ["law-1"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            },
        )()


class ContractReviewTests(unittest.TestCase):
    def test_review_parsed_contract_builds_source_backed_findings_and_edits(self) -> None:
        parse_result = ParseDocumentResult(
            accepted=True,
            reason="ok",
            clause_count=1,
            subclause_count=0,
            paragraphs=[
                ParagraphPreview(
                    node_id="p1",
                    text_excerpt="계약을 위반하면 위약금 1,000만원을 지급한다.",
                    text_length=25,
                    clause_id="c1",
                    clause_no="제1조",
                    writable_as_paragraph=True,
                    run_count=1,
                )
            ],
            clauses=[
                ClauseSummary(
                    clause_id="c1",
                    clause_no="제1조",
                    title="위약금",
                    start_node_id="p1",
                    end_node_id="p1",
                    member_node_ids=["p1"],
                )
            ],
        )
        rag = FakeRagClient()

        result = review_parsed_contract(
            parse_result,
            rag_client=rag,
            generation_client=FakeGenerationClient(),
            config=ContractReviewConfig(include_review_html=False),
        )

        self.assertEqual(len(rag.queries), 1)
        self.assertEqual(rag.queries[0]["intent"], "normative")
        self.assertEqual(len(result.findings), 1)
        finding = result.findings[0]
        self.assertEqual(finding.severity, "high")
        self.assertEqual(finding.sources[0].source_id, "law-1")
        self.assertIsNotNone(finding.annotation)
        self.assertIsNotNone(finding.proposed_edit)
        self.assertEqual(finding.proposed_edit.target_id, "p1")
        self.assertTrue(finding.proposed_edit.expected_text_hash)
        self.assertIn("실제 발생한 손해", finding.proposed_edit.new_text)


if __name__ == "__main__":
    unittest.main()
