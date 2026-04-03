from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = THIS_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from agent.parser import ParserConfig, run_parser
from processor_types import DocIR
from prompts import load_prompt


class StubStructuredLLM:
    def __init__(
        self,
        responses: dict[str, dict] | None = None,
        *,
        boundary_responses: dict[str, dict] | None = None,
    ):
        self.responses = responses or {}
        self.boundary_responses = boundary_responses or {}
        self.payloads: dict[str, dict] = {}
        self.boundary_payloads: dict[str, dict] = {}
        self.boundary_order: list[str] = []

    def with_structured_output(self, _schema, method=None):
        self.method = method
        return self

    def get_num_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def invoke(self, messages):
        payload = json.loads(messages[-1][1])
        unit_id = payload["unit_id"]
        if "position_in_block" in payload:
            self.boundary_payloads[unit_id] = payload
            self.boundary_order.append(unit_id)
            if unit_id in self.boundary_responses:
                return self.boundary_responses[unit_id]
            return {
                "unit_id": unit_id,
                "belongs_to_active_context": True,
                "reason": "default",
            }

        self.payloads[unit_id] = payload
        if unit_id in self.responses:
            return self.responses[unit_id]
        return {
            "unit_id": unit_id,
            "status": "ok",
            "label": "body",
            "candidate_labels": ["body"],
            "reason": "default",
            "ops": [],
        }


class ParserTests(unittest.TestCase):
    def test_prompt_loader_markdown(self) -> None:
        prompt = load_prompt("paragraph_labeler", profile="default")
        self.assertIn("JSON", prompt)
        self.assertIn("unit_id", prompt)

    def test_parser_updates_labels(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제1조 (목적)",
                "s1.p2.r1": "본문 문장",
            }
        )
        llm = StubStructuredLLM(
            {
                "s1.p2": {
                    "unit_id": "s1.p2",
                    "status": "ok",
                    "label": "body",
                    "candidate_labels": ["body"],
                    "reason": "body",
                    "ops": [],
                },
            }
        )

        out = run_parser(
            doc_ir,
            max_concurrency=2,
            llm_model=llm,
            prompt_text="test prompt",
        )
        # s1.p1 has regex_clause → resolved by rules as "clause"
        self.assertEqual(out.paragraphs[0].final_label, "clause")
        # s1.p2 resolved by LLM
        self.assertEqual(out.paragraphs[1].final_label, "body")

    def test_rule_prelabel_clause_subclause(self) -> None:
        """Clause and subclause are resolved by rules, not LLM."""
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제1조 (목적) 본 계약은...",
                "s1.p2.r1": "② 기획업자는...",
                "s1.p3.r1": "일반 본문 텍스트",
            }
        )
        llm = StubStructuredLLM()

        out = run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
        )
        # p1: regex_clause → clause (by rules)
        self.assertEqual(out.paragraphs[0].final_label, "clause")
        # p2: regex_subclause → subclause (by rules)
        self.assertEqual(out.paragraphs[1].final_label, "subclause")
        # p3: no regex signals → goes to LLM → default body
        self.assertEqual(out.paragraphs[2].final_label, "body")
        # Only p3 should have been sent to LLM
        self.assertIn("s1.p3", llm.payloads)
        self.assertNotIn("s1.p1", llm.payloads)
        self.assertNotIn("s1.p2", llm.payloads)

    def test_rule_prelabel_auto_split(self) -> None:
        """Paragraph with both clause and subclause markers gets auto-split."""
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제4조 (학습권 보장) ① 기획업자는 대중문화예술인이...",
            }
        )
        llm = StubStructuredLLM()

        out = run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
        )
        p = out.paragraphs[0]
        # Should have been split into clause + subclause segments
        self.assertGreaterEqual(len(p.segments), 2)
        self.assertEqual(p.segments[0].label, "clause")
        self.assertEqual(p.segments[1].label, "subclause")
        # Should NOT have gone to LLM
        self.assertNotIn("s1.p1", llm.payloads)

    def test_rule_prelabel_disabled(self) -> None:
        """When rule prelabel is disabled, all paragraphs go to LLM."""
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제1조 (목적)",
                "s1.p2.r1": "본문",
            }
        )
        llm = StubStructuredLLM(
            {
                "s1.p1": {
                    "unit_id": "s1.p1",
                    "status": "ok",
                    "label": "clause",
                    "candidate_labels": ["clause"],
                    "reason": "heading",
                    "ops": [],
                },
            }
        )

        out = run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
            parser_config=ParserConfig(enable_rule_prelabel=False),
        )
        self.assertEqual(out.paragraphs[0].final_label, "clause")
        # Both should have been sent to LLM
        self.assertIn("s1.p1", llm.payloads)
        self.assertIn("s1.p2", llm.payloads)

    def test_sliding_window_payload_format(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": " ",
                "s1.p2.r1": "TARGET",
                "s1.p3.r1": "",
                "s1.p4.r1": "RIGHT CONTEXT " * 40,
            }
        )
        llm = StubStructuredLLM()

        out = run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
            parser_config=ParserConfig(context_neighbor_token_budget=8),
        )
        self.assertEqual(out.paragraphs[1].final_label, "body")

        p2_payload = llm.payloads["s1.p2"]
        # New format: flat strings with position
        self.assertEqual(p2_payload["position"], "start")  # p1 is whitespace-only → no prev
        self.assertNotIn("prev", p2_payload)
        self.assertIn("next", p2_payload)  # p4 is right context

    def test_payload_includes_active_numbering_context(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제8조 (제공시간) ① 아래 표에 따른다.",
                "s1.p2.r1": "<표> 제공시간 제한",
            }
        )
        llm = StubStructuredLLM()

        run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
        )

        p2_payload = llm.payloads["s1.p2"]
        self.assertEqual(p2_payload["signals"]["active_clause_no"], "8")
        self.assertEqual(p2_payload["signals"]["active_subclause_no"], "8.1")

    def test_context_boundary_trim_clears_only_trailing_leak_blocks(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제16조 (계약의 실효) 본 계약은 ...",
                "s1.p2.r1": "같은 조의 설명 문장",
                "s1.p3.r1": "계약체결 일시 :      년      월      일",
                "s1.p4.r1": "기획업자",
            }
        )
        llm = StubStructuredLLM(
            {
                "s1.p2": {
                    "unit_id": "s1.p2",
                    "status": "ok",
                    "label": "body",
                    "candidate_labels": ["body"],
                    "reason": "body",
                    "ops": [],
                },
                "s1.p3": {
                    "unit_id": "s1.p3",
                    "status": "ok",
                    "label": "input_block",
                    "candidate_labels": ["input_block"],
                    "reason": "form field",
                    "ops": [],
                },
                "s1.p4": {
                    "unit_id": "s1.p4",
                    "status": "ok",
                    "label": "input_block",
                    "candidate_labels": ["input_block"],
                    "reason": "signature role",
                    "ops": [],
                },
            },
            boundary_responses={
                "s1.p4": {
                    "unit_id": "s1.p4",
                    "belongs_to_active_context": False,
                    "reason": "outside clause",
                },
                "s1.p3": {
                    "unit_id": "s1.p3",
                    "belongs_to_active_context": False,
                    "reason": "outside clause",
                },
                "s1.p2": {
                    "unit_id": "s1.p2",
                    "belongs_to_active_context": True,
                    "reason": "still clause content",
                },
            },
        )

        out = run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
        )

        self.assertEqual(llm.boundary_order, ["s1.p4", "s1.p3", "s1.p2"])
        self.assertEqual(out.paragraphs[1].parser_signals.provisional_clause_no, "16")
        self.assertIsNone(out.paragraphs[2].parser_signals.provisional_clause_no)
        self.assertIsNone(out.paragraphs[3].parser_signals.provisional_clause_no)

    def test_context_boundary_trim_keeps_doc_end_body_when_llm_confirms_it(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제8조 (제공시간) ① 아래 표에 따른다.",
                "s1.p2.r1": "※ 위 표는 개정 내용에 따른다.",
            }
        )
        llm = StubStructuredLLM(
            {
                "s1.p2": {
                    "unit_id": "s1.p2",
                    "status": "ok",
                    "label": "body",
                    "candidate_labels": ["body"],
                    "reason": "note body",
                    "ops": [],
                },
            },
            boundary_responses={
                "s1.p2": {
                    "unit_id": "s1.p2",
                    "belongs_to_active_context": True,
                    "reason": "still tied to the active subclause",
                },
            },
        )

        out = run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
        )

        self.assertEqual(llm.boundary_order, ["s1.p2"])
        self.assertEqual(out.paragraphs[1].parser_signals.provisional_clause_no, "8")
        self.assertEqual(out.paragraphs[1].parser_signals.provisional_subclause_no, "8.1")

    def test_scope_guard_drops_mismatched_unit_and_invalid_anchors(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "AABB",
                "s1.p2.r1": "SECOND",
            }
        )
        llm = StubStructuredLLM(
            {
                # mismatched unit_id should be dropped
                "s1.p1": {
                    "unit_id": "s1.p999",
                    "status": "ok",
                    "label": "body",
                    "candidate_labels": ["body"],
                    "reason": "bad unit",
                    "ops": [],
                },
                # invalid split anchor should be dropped; valid one kept
                "s1.p2": {
                    "unit_id": "s1.p2",
                    "status": "split",
                    "label": "body",
                    "candidate_labels": ["body"],
                    "reason": "mixed",
                    "ops": [
                        {"op": "split_unit", "anchor_text": "NOPE", "occurrence": 1},
                        {"op": "split_unit", "anchor_text": "OND", "occurrence": 1},
                    ],
                },
            }
        )

        out = run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
        )

        # p1 unchanged due mismatched unit in response
        self.assertIsNone(out.paragraphs[0].final_label)

        # p2 split from one valid anchor only -> two segments
        self.assertEqual(out.paragraphs[1].final_label, "body")
        self.assertEqual(len(out.paragraphs[1].segments), 2)

    def test_parser_writes_run_logs(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "테스트 본문",
                "s1.p2.r1": "다음 문단",
            }
        )
        llm = StubStructuredLLM()

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_parser(
                doc_ir,
                llm_model=llm,
                prompt_text="test prompt",
                parser_config=ParserConfig(
                    log_dir=tmp_dir,
                    log_to_console=False,
                ),
            )

            log_files = list(Path(tmp_dir).glob("parser_*.log"))
            self.assertEqual(len(log_files), 1)
            log_text = log_files[0].read_text(encoding="utf-8")
            self.assertIn("parser run start", log_text)
            self.assertIn("parser run complete", log_text)

    def test_parser_logs_llm_input_and_output_when_enabled(self) -> None:
        doc_ir = DocIR.from_mapping({"s1.p1.r1": "단일 문단"})
        llm = StubStructuredLLM(
            {
                "s1.p1": {
                    "unit_id": "s1.p1",
                    "status": "ok",
                    "label": "body",
                    "candidate_labels": ["body"],
                    "reason": "logged",
                    "ops": [],
                }
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_parser(
                doc_ir,
                llm_model=llm,
                prompt_text="test prompt",
                parser_config=ParserConfig(
                    log_dir=tmp_dir,
                    log_to_console=False,
                    log_llm_io=True,
                ),
            )

            log_file = next(Path(tmp_dir).glob("parser_*.log"))
            log_text = log_file.read_text(encoding="utf-8")
            self.assertIn("llm input unit_id=s1.p1", log_text)
            self.assertIn("\"unit_id\": \"s1.p1\"", log_text)
            self.assertIn("llm raw output unit_id=s1.p1", log_text)
            self.assertIn("llm parsed output unit_id=s1.p1", log_text)

    def test_op_normalization(self) -> None:
        """LLM returning 'split_clause' instead of 'split_unit' should be auto-fixed."""
        doc_ir = DocIR.from_mapping({"s1.p1.r1": "AABBCC"})
        llm = StubStructuredLLM(
            {
                "s1.p1": {
                    "unit_id": "s1.p1",
                    "status": "split",
                    "label": "body",
                    "candidate_labels": ["body"],
                    "reason": "mixed",
                    "ops": [
                        {"op": "split_clause", "anchor_text": "BB", "occurrence": 1},
                    ],
                }
            }
        )

        out = run_parser(
            doc_ir,
            llm_model=llm,
            prompt_text="test prompt",
        )
        self.assertEqual(out.paragraphs[0].final_label, "body")
        self.assertEqual(len(out.paragraphs[0].segments), 2)

if __name__ == "__main__":
    unittest.main()
