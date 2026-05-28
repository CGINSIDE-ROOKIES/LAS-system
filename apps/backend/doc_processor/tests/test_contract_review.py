from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from doc_processor.contract_review import (
    ContractReviewGraphState,
    ContractReviewConfig,
    ReviewContractRequest,
    _findings_from_payload,
    _parse_generation_payload,
    _text_hash,
    build_contract_review_graph,
    check_contract_review_env,
    load_and_categorize_contract,
    review_parsed_contract,
    validate_contract_edit_risk,
)
from doc_processor.contract_review import ContractReviewSource
from doc_processor.api_types import ClauseSummary, ParagraphPreview, ParseDocumentResult
from doc_processor.parser_types import ParagraphCategory


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
                                "risk_level": "high",
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


class SequenceGenerationClient:
    def __init__(self, answers: list[str | Exception]) -> None:
        self.answers = answers
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, system_prompt: str | None = None):
        del system_prompt
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.answers) - 1)
        answer = self.answers[index]
        if isinstance(answer, Exception):
            raise answer
        return type("Generation", (), {"answer": answer})()


class ContractReviewTests(unittest.TestCase):
    def _single_clause_parse_result(self) -> ParseDocumentResult:
        return ParseDocumentResult(
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

    def test_review_parsed_contract_builds_source_backed_findings_and_edits(self) -> None:
        parse_result = self._single_clause_parse_result()
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
        self.assertEqual(result.risk_level, "high")
        self.assertEqual(result.clause_risk_counts["high"], 1)
        finding = result.findings[0]
        self.assertEqual(finding.risk_level, "high")
        self.assertEqual(finding.sources[0].source_id, "law-1")
        self.assertIsNotNone(finding.annotation)
        self.assertIn("Sources:", finding.annotation.note)
        self.assertIsNotNone(finding.proposed_edit)
        self.assertEqual(finding.proposed_edit.target_id, "p1")
        self.assertTrue(finding.proposed_edit.expected_text_hash)
        self.assertIn("실제 발생한 손해", finding.proposed_edit.new_text)
        self.assertEqual(len(result.hitl_requests), 1)
        self.assertEqual(result.hitl_requests[0].kind, "suggested_edit")
        self.assertIn("--- current", result.hitl_requests[0].diff or "")

    def test_validate_contract_edit_risk_reuses_clause_risk_pipeline(self) -> None:
        parse_result = self._single_clause_parse_result()
        candidate_text = "계약을 위반하면 위약금 2,000만원을 지급한다."
        answer = json.dumps(
            {
                "findings": [
                    {
                        "risk_level": "mid",
                        "issue_type": "penalty_clause",
                        "title": "위약금 예정 조항",
                        "target_node_id": "p1",
                        "selected_text": "위약금 2,000만원을 지급한다",
                        "rationale": "위약 예정 금지와 충돌할 수 있다.",
                        "recommendation": "실손해 기준으로 수정한다.",
                        "replacement_text": "실제 발생한 손해에 한해 배상한다",
                        "source_ids": ["law-1"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        rag = FakeRagClient()

        result = validate_contract_edit_risk(
            parse_result,
            target_node_id="p1",
            candidate_text=candidate_text,
            rag_client=rag,
            generation_client=SequenceGenerationClient([answer]),
            config=ContractReviewConfig(include_review_html=False),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.risk_level, "mid")
        self.assertIn("위약금 예정 조항", result.reason)
        self.assertEqual(len(rag.queries), 1)
        self.assertIn(candidate_text, str(rag.queries[0]["search_query"]))

    def test_validate_contract_edit_risk_allows_low_risk_candidate(self) -> None:
        answer = json.dumps(
            {
                "findings": [
                    {
                        "risk_level": "low",
                        "issue_type": "drafting_clarity",
                        "title": "통지 방식 명확화",
                        "target_node_id": "p1",
                        "selected_text": "서면으로 통지한다",
                        "rationale": "통지 방식 보완이 있으면 더 명확하다.",
                        "recommendation": "주소와 기한을 명확히 한다.",
                        "replacement_text": "서면으로 7일 전에 통지한다",
                        "source_ids": ["law-1"],
                    }
                ]
            },
            ensure_ascii=False,
        )

        result = validate_contract_edit_risk(
            self._single_clause_parse_result(),
            target_node_id="p1",
            candidate_text="계약 해지는 서면으로 통지한다.",
            rag_client=FakeRagClient(),
            generation_client=SequenceGenerationClient([answer]),
            config=ContractReviewConfig(include_review_html=False),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.risk_level, "low")

    def test_review_generation_repairs_invalid_json_before_fallback(self) -> None:
        valid_answer = json.dumps(
            {
                "findings": [
                    {
                        "risk_level": "high",
                        "issue_type": "penalty_clause",
                        "title": "위약금 예정 조항",
                        "target_node_id": "p1",
                        "selected_text": "위약금 1,000만원을 지급한다",
                        "rationale": "위약 예정 금지와 충돌할 수 있다.",
                        "recommendation": "실손해 기준으로 수정한다.",
                        "replacement_text": "실제 발생한 손해에 한해 관련 법령에 따라 배상한다",
                        "source_ids": ["law-1"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        generation = SequenceGenerationClient(["not json", valid_answer])

        result = review_parsed_contract(
            self._single_clause_parse_result(),
            rag_client=FakeRagClient(),
            generation_client=generation,
            config=ContractReviewConfig(include_review_html=False),
        )

        self.assertEqual(len(generation.prompts), 2)
        self.assertIn("[validation_failures]", generation.prompts[1])
        self.assertEqual(len(result.findings), 1)
        self.assertIn("Review generation repaired after 2 attempts.", result.warnings)

    def test_review_generation_retries_retryable_provider_error(self) -> None:
        valid_answer = json.dumps(
            {
                "findings": [
                    {
                        "risk_level": "high",
                        "issue_type": "penalty_clause",
                        "title": "위약금 예정 조항",
                        "target_node_id": "p1",
                        "selected_text": "위약금 1,000만원을 지급한다",
                        "rationale": "위약 예정 금지와 충돌할 수 있다.",
                        "recommendation": "실손해 기준으로 수정한다.",
                        "replacement_text": "실제 발생한 손해에 한해 관련 법령에 따라 배상한다",
                        "source_ids": ["law-1"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        generation = SequenceGenerationClient(
            [
                RuntimeError("HTTP 503 UNAVAILABLE: This model is currently experiencing high demand."),
                valid_answer,
            ]
        )

        result = review_parsed_contract(
            self._single_clause_parse_result(),
            rag_client=FakeRagClient(),
            generation_client=generation,
            config=ContractReviewConfig(
                include_review_html=False,
                generation_provider_retry_base_delay_sec=0,
            ),
        )

        self.assertEqual(len(generation.prompts), 2)
        self.assertEqual(len(result.findings), 1)

    def test_review_generation_falls_back_after_repair_attempts(self) -> None:
        answer = json.dumps(
            {
                "findings": [
                    {
                        "risk_level": "high",
                        "issue_type": "penalty_clause",
                        "title": "위약금 예정 조항",
                        "target_node_id": "p1",
                        "selected_text": "없는 문구",
                        "rationale": "위약 예정 금지와 충돌할 수 있다.",
                        "recommendation": "실손해 기준으로 수정한다.",
                        "replacement_text": "실제 손해",
                        "source_ids": ["law-1"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        generation = SequenceGenerationClient([answer])

        result = review_parsed_contract(
            self._single_clause_parse_result(),
            rag_client=FakeRagClient(),
            generation_client=generation,
            config=ContractReviewConfig(include_review_html=False, max_generation_repair_attempts=3),
        )

        self.assertEqual(len(generation.prompts), 3)
        self.assertEqual(len(result.findings), 1)
        self.assertIsNone(result.findings[0].proposed_edit)
        self.assertTrue(any("validation still failed after 3 attempts" in warning for warning in result.warnings))

    def test_review_generation_repairs_overbroad_neighbor_paragraph_edit(self) -> None:
        parse_result = ParseDocumentResult(
            accepted=True,
            reason="ok",
            clause_count=1,
            subclause_count=2,
            paragraphs=[
                ParagraphPreview(
                    node_id="p2",
                    text_excerpt="2. 입사 후 3개월은 업무적응 기간으로 한다.",
                    text_length=24,
                    category=ParagraphCategory.SUBCLAUSE_HEADING,
                    clause_id="c2",
                    clause_no="2",
                    subclause_id="s2",
                    subclause_no="2",
                    writable_as_paragraph=True,
                    run_count=1,
                ),
                ParagraphPreview(
                    node_id="p3",
                    text_excerpt="3. 수습기간 중 평가는 객관적 평가자료에 따른다.",
                    text_length=28,
                    category=ParagraphCategory.SUBCLAUSE_HEADING,
                    clause_id="c2",
                    clause_no="2",
                    subclause_id="s3",
                    subclause_no="3",
                    writable_as_paragraph=True,
                    run_count=1,
                ),
            ],
            clauses=[
                ClauseSummary(
                    clause_id="c2",
                    clause_no="제2조",
                    title="수습",
                    start_node_id="p2",
                    end_node_id="p3",
                    member_node_ids=["p2", "p3"],
                )
            ],
        )
        unsafe_answer = json.dumps(
            {
                "findings": [
                    {
                        "risk_level": "low",
                        "title": "수습 평가 기준 보완",
                        "target_node_id": "p3",
                        "selected_text": "3. 수습기간 중 평가는 객관적 평가자료에 따른다.",
                        "rationale": "기준이 불명확하다.",
                        "recommendation": "평가 기준을 명확히 한다.",
                        "full_replacement_text": (
                            "2. 입사 후 3개월은 업무적응 기간으로 한다.\n"
                            "3. 수습기간 중 평가는 업무 성과, 근태 등 객관적 평가자료에 따른다."
                        ),
                        "source_ids": ["law-1"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        safe_answer = json.dumps(
            {
                "findings": [
                    {
                        "risk_level": "low",
                        "title": "수습 평가 기준 보완",
                        "target_node_id": "p3",
                        "selected_text": "3. 수습기간 중 평가는 객관적 평가자료에 따른다.",
                        "rationale": "기준이 불명확하다.",
                        "recommendation": "평가 기준을 명확히 한다.",
                        "full_replacement_text": "3. 수습기간 중 평가는 업무 성과, 근태 등 객관적 평가자료에 따른다.",
                        "source_ids": ["law-1"],
                    }
                ]
            },
            ensure_ascii=False,
        )
        generation = SequenceGenerationClient([unsafe_answer, safe_answer])

        result = review_parsed_contract(
            parse_result,
            rag_client=FakeRagClient(),
            generation_client=generation,
            config=ContractReviewConfig(include_review_html=False),
        )

        self.assertEqual(len(generation.prompts), 2)
        self.assertIn("neighboring paragraph", generation.prompts[1])
        self.assertEqual(result.findings[0].proposed_edit.target_id, "p3")
        self.assertNotIn("2. 입사 후", result.findings[0].proposed_edit.new_text)

    def test_findings_strip_unsafe_clause_heading_body_edit_on_fallback(self) -> None:
        clause = ClauseSummary(
            clause_id="c5",
            clause_no="제5조",
            title="임금",
            start_node_id="p-heading",
            end_node_id="p-body",
            member_node_ids=["p-heading", "p-body"],
        )
        paragraphs = [
            ParagraphPreview(
                node_id="p-heading",
                text_excerpt="제5조(임금 및 지급방법)",
                text_length=14,
                category=ParagraphCategory.CLAUSE_HEADING,
                clause_id="c5",
                clause_no="5",
                writable_as_paragraph=True,
                run_count=1,
            ),
            ParagraphPreview(
                node_id="p-body",
                text_excerpt="1. 월 임금은 세전 3,200,000원으로 한다.",
                text_length=25,
                category=ParagraphCategory.SUBCLAUSE_HEADING,
                clause_id="c5",
                clause_no="5",
                subclause_id="s1",
                subclause_no="1",
                writable_as_paragraph=True,
                run_count=1,
            ),
        ]
        sources = [
            ContractReviewSource(
                rank=1,
                source_id="law-1",
                citation="근로기준법 시행령 제27조의2",
                text="임금 구성항목별 금액을 기재해야 한다.",
            )
        ]
        payload = {
            "findings": [
                {
                    "risk_level": "low",
                    "target_node_id": "p-heading",
                    "selected_text": "제5조(임금 및 지급방법)",
                    "title": "임금 구성항목 보완",
                    "rationale": "구성항목 금액이 필요하다.",
                    "recommendation": "본문 조항을 보완한다.",
                    "full_replacement_text": "1. 월 임금은 세전 3,200,000원으로 한다.",
                    "source_ids": ["law-1"],
                }
            ]
        }

        findings = _findings_from_payload(
            payload,
            clause=clause,
            paragraphs=paragraphs,
            sources=sources,
            max_sources=1,
        )

        self.assertEqual(len(findings), 1)
        self.assertIsNone(findings[0].proposed_edit)

    def test_contract_review_graph_pauses_and_resumes_for_hitl(self) -> None:
        parse_result = self._single_clause_parse_result()
        graph = build_contract_review_graph(checkpointer=InMemorySaver())
        config = {
            "configurable": {
                "thread_id": "contract-review-hitl-test",
                "rag_client": FakeRagClient(),
                "generation_client": FakeGenerationClient(),
            }
        }

        first = graph.invoke(
            ContractReviewGraphState(
                parse_result=parse_result,
                config=ContractReviewConfig(include_review_html=False, pause_for_hitl=True),
            ),
            config=config,
        )

        self.assertIn("__interrupt__", first)
        request = first["__interrupt__"][0].value["requests"][0]
        self.assertEqual(request["kind"], "suggested_edit")

        second = graph.invoke(
            Command(resume={"decisions": [{"finding_id": request["finding_id"], "action": "accept"}]}),
            config=config,
        )
        state = ContractReviewGraphState.model_validate(second)

        self.assertIsNotNone(state.result)
        self.assertEqual(state.result.findings[0].status, "accepted")
        self.assertEqual(state.result.human_decisions[0].action, "accept")

    def test_env_status_checks_rag_env(self) -> None:
        with patch("doc_processor.contract_review.ensure_local_env_loaded", lambda: None):
            with patch.dict(
                os.environ,
                {
                    "QDRANT_URL": "http://qdrant.test",
                    "QDRANT_COLLECTIONS": "law_article,legal_case",
                    "EMBEDDING_API_KEY": "embedding-key",
                    "EMBEDDING_DIMENSIONS": "1024",
                    "LLM_PROVIDER": "gemini",
                    "LLM_MODEL": "gemini-2.5-flash-lite",
                    "LLM_API_KEY": "gemini-key",
                },
                clear=True,
            ):
                status = check_contract_review_env()

        self.assertTrue(status.ready)
        self.assertEqual(status.missing, [])
        self.assertEqual(status.llm_provider, "gemini")
        self.assertEqual(status.llm_model, "gemini-2.5-flash-lite")
        self.assertEqual(status.qdrant_collections, ["law_article", "legal_case"])
        self.assertEqual(status.embedding_dimensions, 1024)

    def test_load_and_categorize_forwards_parser_concurrency(self) -> None:
        captured: dict[str, object] = {}

        def fake_parse_document(**kwargs):
            captured.update(kwargs)
            return self._single_clause_parse_result()

        with patch("doc_processor.contract_review.parse_document", fake_parse_document):
            command = load_and_categorize_contract(
                ContractReviewGraphState(
                    request=ReviewContractRequest(
                        source_path="sample.docx",
                        parser_max_concurrent_workers=2,
                        config=ContractReviewConfig(include_review_html=False),
                    )
                )
            )

        self.assertEqual(captured["max_concurrent_workers"], 2)
        self.assertEqual(command.goto, "prepare_risk_reviews")

    def test_generation_payload_parser_tolerates_trailing_text(self) -> None:
        payload, warning = _parse_generation_payload(
            '{"findings": [{"risk_level": "low"}]}\n\nextra explanation'
        )

        self.assertEqual(payload["findings"][0]["risk_level"], "low")
        self.assertEqual(warning, "Ignored trailing text after review generation JSON.")

    def test_findings_resolve_invalid_target_id_before_building_edit(self) -> None:
        clause = ClauseSummary(
            clause_id="c1",
            clause_no="제1조",
            title="근로시간",
            start_node_id="p1",
            end_node_id="p1",
            member_node_ids=["p1"],
        )
        paragraph = ParagraphPreview(
            node_id="p1",
            text_excerpt="1. 근로시간은 주 40시간으로 한다.",
            text_length=21,
            clause_id="c1",
            subclause_id="s1",
            writable_as_paragraph=True,
            run_count=1,
        )
        sources = [
            ContractReviewSource(
                rank=1,
                source_id="law-1",
                citation="근로기준법 제50조",
                text="근로시간은 휴게시간을 제외하고 주 40시간을 초과할 수 없다.",
            )
        ]
        payload = {
            "findings": [
                {
                    "risk_level": "mid",
                    "target_node_id": "p-missing",
                    "title": "근로시간 조항 보완",
                    "rationale": "법정 근로시간 근거와 비교가 필요하다.",
                    "recommendation": "휴게시간 제외 기준을 명시한다.",
                    "full_replacement_text": "1. 근로시간은 휴게시간을 제외하고 주 40시간으로 한다.",
                    "source_ids": ["law-1"],
                }
            ]
        }

        findings = _findings_from_payload(
            payload,
            clause=clause,
            paragraphs=[paragraph],
            sources=sources,
            max_sources=1,
        )

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.target_node_ids, ["p1"])
        self.assertIsNotNone(finding.annotation)
        self.assertEqual(finding.annotation.target_id, "p1")
        self.assertIsNotNone(finding.proposed_edit)
        self.assertEqual(finding.proposed_edit.target_id, "p1")
        self.assertEqual(finding.proposed_edit.expected_text_hash, _text_hash(paragraph.text_excerpt))


if __name__ == "__main__":
    unittest.main()
