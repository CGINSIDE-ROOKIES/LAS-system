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
    def __init__(self, responses: dict[str, dict] | None = None):
        self.responses = responses or {}
        self.payloads: dict[str, dict] = {}

    def with_structured_output(self, _schema, method=None):
        self.method = method
        return self

    def get_num_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    def invoke(self, messages):
        payload = json.loads(messages[-1][1])
        unit_id = payload["target_unit_id"]
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
        self.assertIn("target_unit_id", prompt)

    def test_parser_updates_labels(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제1조 (목적)",
                "s1.p2.r1": "본문 문장",
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
        self.assertEqual(out.paragraphs[0].final_label, "clause")
        self.assertEqual(out.paragraphs[1].final_label, "body")

    def test_sliding_window_skips_empty_and_marks_boundaries(self) -> None:
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
        self.assertIn("[START_OF_FILE]", p2_payload["left_context"]["markers"])
        self.assertEqual(p2_payload["right_context"]["unit_id"], "s1.p4")
        self.assertIn("[RIGHT_CONTEXT_CLIPPED]", p2_payload["right_context"]["markers"])

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
            self.assertIn("worker start", log_text)
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
            self.assertIn("\"target_unit_id\": \"s1.p1\"", log_text)
            self.assertIn("llm raw output unit_id=s1.p1", log_text)
            self.assertIn("llm parsed output unit_id=s1.p1", log_text)


if __name__ == "__main__":
    unittest.main()
