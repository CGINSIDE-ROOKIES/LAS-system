from __future__ import annotations

import unittest
from pathlib import Path

from document_processor import DocIR, ParaStyleInfo

from doc_processor import ParserConfig, WorkflowState
from doc_processor.parser.boundaries import detect_boundary_suspects, review_boundary_suspects_with_llm
from doc_processor.parser.converters import clause_entry_to_targets, resolve_clause_entry
from doc_processor.parser.graph import build_parser_graph
from doc_processor.parser.parser import parse_document_structure
from doc_processor.parser_types import ParagraphCategory, RelevanceMode


ROOT = Path(__file__).resolve().parents[1]
DOC_SAMPLES = ROOT / "tests" / "doc_samples" / "new_test"
STANDARD_CONTRACT_SAMPLES = ROOT / "tests" / "doc_samples" / "표준계약서모음(hwp-hwpx)"


class FakeStructuredResponder:
    def __init__(self, outputs: dict[str, dict]):
        self.outputs = outputs
        self.calls: list[dict] = []

    def invoke_structured(self, *, profile, prompt, payload, schema):
        self.calls.append({"profile": profile, "prompt": prompt, "payload": payload, "schema": schema})
        if "suspect_blocks" in payload:
            reviews: list[dict] = []
            for block in payload["suspect_blocks"]:
                for node_id in block["suspect_node_ids"]:
                    template = self.outputs.get(node_id, self.outputs.get("__default__", {}))
                    review = dict(template)
                    review["node_id"] = node_id
                    reviews.append(review)
            return schema.model_validate({"reviews": reviews})
        key = payload.get("node_id") or payload.get("title") or "__default__"
        output = self.outputs.get(key, self.outputs.get("__default__", {}))
        return schema.model_validate(output)


def _paragraph_by_anchor(doc: DocIR, debug_path: str):
    for paragraph in doc.paragraphs:
        anchor = paragraph.native_anchor
        if anchor is not None and anchor.debug_path == debug_path:
            return paragraph
    raise KeyError(debug_path)


def _node_id_by_anchor(doc: DocIR, debug_path: str) -> str:
    node_id = _paragraph_by_anchor(doc, debug_path).node_id
    if node_id is None:
        raise AssertionError(f"Paragraph {debug_path} has no node_id.")
    return node_id


class ParserGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = build_parser_graph()

    def _invoke_state(self, state: WorkflowState) -> WorkflowState:
        result = self.graph.invoke(state)
        return WorkflowState.model_validate(result)

    def test_hwpx_contract_detects_article_and_circled_rules(self) -> None:
        state = self._invoke_state(
            WorkflowState(
                target_file=DOC_SAMPLES / "02. 청소년 대중문화예술인 표준 부속합의서.hwpx",
                parser_config=ParserConfig(boundary_review_enabled=False, label_review_enabled=False),
            )
        )
        self.assertTrue(state.parser_result.accepted)
        self.assertEqual(state.parser_result.clause_rule_name, "article")
        self.assertEqual(state.parser_result.subclause_rule_name, "circled")
        self.assertGreaterEqual(state.parser_result.clause_count, 10)
        self.assertEqual(_paragraph_by_anchor(state.working_doc, "s1.p8").meta.parser.category, ParagraphCategory.CLAUSE_HEADING)
        self.assertEqual(_paragraph_by_anchor(state.working_doc, "s1.p16").meta.parser.category, ParagraphCategory.SUBCLAUSE_HEADING)

    def test_global_subclause_rule_prefers_circled_over_definition_list_numeric(self) -> None:
        state = self._invoke_state(
            WorkflowState(
                target_file=STANDARD_CONTRACT_SAMPLES / "04. 2차적저작물작성권 양도계약서.hwp",
                parser_config=ParserConfig(
                    relevance_mode=RelevanceMode.DISABLED,
                    boundary_review_enabled=False,
                    label_review_enabled=False,
                ),
            )
        )
        self.assertTrue(state.parser_result.accepted)
        self.assertEqual(state.parser_result.subclause_rule_name, "circled")
        self.assertEqual(_paragraph_by_anchor(state.working_doc, "s1.p11").meta.parser.category, ParagraphCategory.CLAUSE_BODY)
        self.assertEqual(_paragraph_by_anchor(state.working_doc, "s1.p17").meta.parser.category, ParagraphCategory.CLAUSE_BODY)
        self.assertEqual(_paragraph_by_anchor(state.working_doc, "s1.p21").meta.parser.category, ParagraphCategory.SUBCLAUSE_HEADING)

    def test_boundary_batch_payload_preserves_immediate_blank_separator_context(self) -> None:
        target = STANDARD_CONTRACT_SAMPLES / "04. 2차적저작물작성권 양도계약서.hwp"
        doc = DocIR.from_file(target)
        analysis = detect_boundary_suspects(parse_document_structure(doc))
        responder = FakeStructuredResponder(
            {
                "__default__": {
                    "action": "keep",
                    "reason": "Payload capture.",
                    "anchor_text": None,
                    "occurrence": 1,
                }
            }
        )
        review_boundary_suspects_with_llm(
            doc,
            analysis,
            ParserConfig(boundary_model_override=responder),
        )
        blocks = responder.calls[0]["payload"]["suspect_blocks"]
        target_node_id = _node_id_by_anchor(doc, "s1.p85")
        previous_node_id = _node_id_by_anchor(doc, "s1.p84")
        block = next(item for item in blocks if target_node_id in item["suspect_node_ids"])
        paragraphs = block["paragraphs"]
        target_index = next(index for index, paragraph in enumerate(paragraphs) if paragraph["node_id"] == target_node_id)
        self.assertEqual(paragraphs[target_index - 1]["node_id"], previous_node_id)
        self.assertEqual(paragraphs[target_index - 1]["text"], "")
        self.assertIn("_____년 __월 __일", [paragraph["text"] for paragraph in paragraphs[target_index + 1 :]])

    def test_keyword_relevance_rejects_non_contract_notice(self) -> None:
        state = self._invoke_state(
            WorkflowState(
                target_file=DOC_SAMPLES / "2026년_전통시장_육성사업(백년시장)_모집공고(수정).hwpx",
                parser_config=ParserConfig(
                    relevance_mode=RelevanceMode.KEYWORD_ONLY,
                    boundary_review_enabled=False,
                    label_review_enabled=False,
                ),
            )
        )
        self.assertFalse(state.parser_result.accepted)
        self.assertIsNotNone(state.working_doc.meta.parser_doc.relevance)
        self.assertFalse(state.working_doc.meta.parser_doc.relevance.is_relevant)

    def test_relevance_disabled_keeps_non_contract_document(self) -> None:
        state = self._invoke_state(
            WorkflowState(
                target_file=DOC_SAMPLES / "2026년_전통시장_육성사업(백년시장)_모집공고(수정).hwpx",
                parser_config=ParserConfig(
                    relevance_mode=RelevanceMode.DISABLED,
                    boundary_review_enabled=False,
                    label_review_enabled=False,
                ),
            )
        )
        self.assertTrue(state.parser_result.accepted)
        self.assertEqual(state.parser_result.relevance.mode, RelevanceMode.DISABLED)

    def test_clause_entries_round_trip_to_docir_targets(self) -> None:
        doc = DocIR.from_mapping(
            {
                "s1.p1.r1": "표준근로계약서",
                "s1.p2.r1": "당사자는 다음과 같이 계약을 체결한다.",
                "s1.p3.r1": "제1조 (목적) ① 갑은 을에게 업무를 위탁한다.",
                "s1.p4.r1": "② 을은 성실히 업무를 수행한다.",
                "s1.p5.r1": "제2조 (기간) 계약기간은 1년으로 한다.",
            }
        )
        state = self._invoke_state(
            WorkflowState(
                base_doc=doc,
                working_doc=doc,
                parser_config=ParserConfig(
                    relevance_mode=RelevanceMode.DISABLED,
                    boundary_review_enabled=False,
                    label_review_enabled=False,
                ),
            )
        )
        entries = state.working_doc.meta.parser_doc.clause_entries
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].subclauses[0].subclause_no, "1")
        targets = clause_entry_to_targets(entries[0])
        expected_node_ids = [_node_id_by_anchor(state.working_doc, "s1.p3"), _node_id_by_anchor(state.working_doc, "s1.p4")]
        self.assertEqual([target.node_id for target in targets], expected_node_ids)
        resolved = resolve_clause_entry(state.working_doc, entries[0])
        self.assertEqual([paragraph.node_id for paragraph in resolved], expected_node_ids)

    def test_keyword_then_llm_uses_override_for_ambiguous_doc(self) -> None:
        doc = DocIR.from_mapping(
            {
                "s1.p1.r1": "문서",
                "s1.p2.r1": "안내문",
                "s1.p3.r1": "본문",
            }
        )
        responder = FakeStructuredResponder(
            {
                "__default__": {
                    "is_relevant": True,
                    "doc_kind": "contract",
                    "reason": "Ambiguous keyword result, but the sampled text is intended as a contract.",
                    "confidence": 0.7,
                }
            }
        )
        state = self._invoke_state(
            WorkflowState(
                base_doc=doc,
                working_doc=doc,
                parser_config=ParserConfig(
                    relevance_mode=RelevanceMode.KEYWORD_THEN_LLM,
                    relevance_model_override=responder,
                    boundary_review_enabled=False,
                    label_review_enabled=False,
                ),
            )
        )
        self.assertTrue(state.parser_result.accepted)
        self.assertTrue(state.parser_result.relevance.llm_used)

    def test_boundary_and_label_llm_review_can_detach_and_relabel(self) -> None:
        doc = DocIR.from_mapping(
            {
                "s1.p1.r1": "표준계약서",
                "s1.p2.r1": "제1조 (목적) 계약의 목적을 정한다.",
                "s1.p3.r1": "계약의 세부 조건은 다음과 같다.",
                "s1.p4.r1": "[별표1]",
            }
        )
        doc.paragraphs[0].para_style = ParaStyleInfo(align="center")
        p2_node_id = _node_id_by_anchor(doc, "s1.p2")
        p3_node_id = _node_id_by_anchor(doc, "s1.p3")
        p4_node_id = _node_id_by_anchor(doc, "s1.p4")
        boundary_responder = FakeStructuredResponder(
            {
                p2_node_id: {"node_id": p2_node_id, "action": "keep", "reason": "Clause heading remains part of the clause.", "anchor_text": None, "occurrence": 1},
                p3_node_id: {"node_id": p3_node_id, "action": "keep", "reason": "Clause body remains part of the clause.", "anchor_text": None, "occurrence": 1},
                p4_node_id: {"node_id": p4_node_id, "action": "detach", "reason": "Appendix marker should not inherit the clause.", "anchor_text": None, "occurrence": 1},
            }
        )
        label_responder = FakeStructuredResponder(
            {
                p4_node_id: {
                    "node_id": p4_node_id,
                    "status": "ok",
                    "label": "appendix",
                    "candidate_labels": ["appendix"],
                    "reason": "Standalone appendix marker.",
                    "ops": [],
                }
            }
        )
        state = self._invoke_state(
            WorkflowState(
                base_doc=doc,
                working_doc=doc,
                parser_config=ParserConfig(
                    relevance_mode=RelevanceMode.DISABLED,
                    boundary_model_override=boundary_responder,
                    label_model_override=label_responder,
                ),
            )
        )
        self.assertEqual(len(boundary_responder.calls), 1)
        self.assertIn("suspect_blocks", boundary_responder.calls[0]["payload"])
        p4 = _paragraph_by_anchor(state.working_doc, "s1.p4")
        self.assertIsNone(p4.meta.parser.clause_id)
        self.assertIsNone(p4.meta.parser.clause_no)
        self.assertIsNone(p4.meta.parser.subclause_id)
        self.assertIsNone(p4.meta.parser.subclause_no)
        self.assertEqual(p4.meta.parser.category, ParagraphCategory.APPENDIX)
        self.assertEqual(p4.meta.parser.spans, [])
        clause_entry = state.working_doc.meta.parser_doc.clause_entries[0]
        self.assertEqual(clause_entry.member_node_ids, [p2_node_id, p3_node_id])

    def test_clause_owned_tables_and_input_like_paragraphs_stay_clause_body(self) -> None:
        doc = DocIR.from_mapping(
            {
                "s1.p1.r1": "표준계약서",
                "s1.p2.r1": "제1조 (제출자료)",
                "s1.p3.tbl1.tr1.tc1.p1.r1": "성명",
                "s1.p3.tbl1.tr1.tc2.p1.r1": "홍길동",
                "s1.p4.r1": "연락처: __________________",
                "s1.p5.r1": "제2조 (기타) 기타사항은 별도로 정한다.",
            }
        )
        boundary_responder = FakeStructuredResponder(
            {
                "__default__": {
                    "node_id": "ignored",
                    "action": "keep",
                    "reason": "Still part of the active clause context.",
                    "anchor_text": None,
                    "occurrence": 1,
                }
            }
        )
        state = self._invoke_state(
            WorkflowState(
                base_doc=doc,
                working_doc=doc,
                parser_config=ParserConfig(
                    relevance_mode=RelevanceMode.DISABLED,
                    boundary_model_override=boundary_responder,
                    label_review_enabled=False,
                ),
            )
        )
        self.assertEqual(_paragraph_by_anchor(state.working_doc, "s1.p3").meta.parser.category, ParagraphCategory.CLAUSE_BODY)
        self.assertEqual(_paragraph_by_anchor(state.working_doc, "s1.p4").meta.parser.category, ParagraphCategory.CLAUSE_BODY)
        self.assertEqual(_paragraph_by_anchor(state.working_doc, "s1.p3").tables[0].meta.parser.category, ParagraphCategory.CLAUSE_BODY)


if __name__ == "__main__":
    unittest.main()
