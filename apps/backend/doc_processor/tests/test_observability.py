from __future__ import annotations

import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from document_processor import DocIR
from pydantic import BaseModel

from doc_processor.main import run_parser
from doc_processor.observability.langfuse import _sanitize_langfuse_payload
from doc_processor.parser.llm_utils import invoke_structured_model
from doc_processor.parser_types import ClauseEntry, ParagraphAnalysis, ParagraphCategory, ParserAnalysis
from doc_processor.state import ParserConfig, WorkflowState


class StructuredOutput(BaseModel):
    value: str


class FakeStructuredRunnable:
    def __init__(self) -> None:
        self.last_prompt = None
        self.last_config = None

    def invoke(self, prompt, config=None):
        self.last_prompt = prompt
        self.last_config = config
        return {"value": "ok"}


class FakeChatModel:
    def __init__(self) -> None:
        self.structured = FakeStructuredRunnable()

    def with_structured_output(self, schema, method=None):
        return self.structured


class FakeGraph:
    def __init__(self, result) -> None:
        self.result = result
        self.last_initial = None
        self.last_config = None

    def invoke(self, initial, config=None):
        self.last_initial = initial
        self.last_config = config
        return self.result


@contextmanager
def _fake_langfuse_context(_config, *, source):
    del source
    yield {}


class ObservabilityTests(unittest.TestCase):
    def test_sanitize_langfuse_payload_summarizes_workflow_state(self) -> None:
        doc = DocIR.from_mapping({"s1.p1.r1": "표준계약서"})
        analysis = ParserAnalysis(
            clause_rule_name="article",
            subclause_rule_name="numeric_dot",
            paragraphs=[
                ParagraphAnalysis(
                    unit_id="p1",
                    text="제1조 목적",
                    category=ParagraphCategory.CLAUSE_HEADING,
                    clause_id="c1",
                    clause_no="1",
                ),
                ParagraphAnalysis(
                    unit_id="p2",
                    text="계약의 목적은 다음과 같다.",
                    category=ParagraphCategory.CLAUSE_BODY,
                    clause_id="c1",
                    clause_no="1",
                ),
            ],
            clause_entries=[
                ClauseEntry(
                    clause_id="c1",
                    clause_no="1",
                    start_unit_id="p1",
                    end_unit_id="p2",
                )
            ],
            boundary_suspect_unit_ids=["p2"],
            ambiguous_label_unit_ids=["p2"],
            notes=["Detected clause numbering."],
        )
        state = WorkflowState(
            base_doc=doc,
            working_doc=doc,
            parser_analysis=analysis,
            parser_config=ParserConfig(boundary_review_enabled=False, label_review_enabled=True),
            boundary_review_results=[{"unit_id": "p2", "review": {"action": "keep"}}],
            errors=["timeout waiting for label review"],
        )

        payload = _sanitize_langfuse_payload({"state": state})
        sanitized_state = payload["state"]

        self.assertEqual(sanitized_state["_excluded_type"], "WorkflowState")
        self.assertEqual(sanitized_state["base_doc"]["_excluded_type"], "DocIR")
        self.assertEqual(sanitized_state["base_doc"]["paragraph_count"], 1)
        self.assertNotIn("paragraphs", sanitized_state["base_doc"])
        self.assertEqual(sanitized_state["working_doc"]["_excluded_type"], "DocIR")
        self.assertEqual(sanitized_state["parser_analysis"]["_excluded_type"], "ParserAnalysis")
        self.assertEqual(sanitized_state["parser_analysis"]["paragraph_count"], 2)
        self.assertEqual(sanitized_state["parser_analysis"]["clause_count"], 1)
        self.assertEqual(
            sanitized_state["parser_analysis"]["paragraph_category_counts"],
            {
                ParagraphCategory.CLAUSE_HEADING.value: 1,
                ParagraphCategory.CLAUSE_BODY.value: 1,
            },
        )
        self.assertNotIn("paragraphs", sanitized_state["parser_analysis"])
        self.assertEqual(sanitized_state["boundary_review_results"]["count"], 1)
        self.assertFalse(sanitized_state["parser_config"]["boundary_review_enabled"])
        self.assertTrue(sanitized_state["parser_config"]["label_review_enabled"])
        self.assertEqual(sanitized_state["errors"]["count"], 1)

    def test_sanitize_langfuse_payload_summarizes_mapping_shapes(self) -> None:
        payload = _sanitize_langfuse_payload(
            {
                "state": {
                    "target_file": "sample.hwp",
                    "parser_config": {"boundary_review_enabled": True},
                    "parser_analysis": {
                        "clause_rule_name": "article",
                        "paragraphs": [
                            {"unit_id": "p1", "text": "제1조 목적", "category": "clause_heading"},
                            {"unit_id": "p2", "text": "본문", "category": "clause_body"},
                        ],
                        "clause_entries": [{"clause_id": "c1"}],
                        "boundary_suspect_unit_ids": ["p2"],
                        "ambiguous_label_unit_ids": [],
                        "notes": ["Detected clause numbering."],
                    },
                    "parser_result": {
                        "accepted": True,
                        "reason": "done",
                        "clause_count": 1,
                        "subclause_count": 0,
                        "boundary_suspect_unit_ids": ["p2"],
                        "ambiguous_label_unit_ids": [],
                        "notes": [],
                    },
                    "messages": [{"kind": "debug"}],
                }
            }
        )

        sanitized_state = payload["state"]
        self.assertEqual(sanitized_state["_excluded_type"], "WorkflowState")
        self.assertEqual(sanitized_state["parser_analysis"]["_excluded_type"], "ParserAnalysis")
        self.assertEqual(sanitized_state["parser_analysis"]["paragraph_count"], 2)
        self.assertNotIn("paragraphs", sanitized_state["parser_analysis"])
        self.assertEqual(sanitized_state["parser_result"]["_excluded_type"], "ParserResult")
        self.assertEqual(sanitized_state["message_count"], 1)

    def test_invoke_structured_model_passes_langfuse_invoke_config(self) -> None:
        fake_model = FakeChatModel()
        with (
            patch("doc_processor.parser.llm_utils.get_chat_model", return_value=fake_model) as get_chat_model,
            patch("doc_processor.parser.llm_utils.get_langchain_invoke_config", return_value={"callbacks": ["cb"]}),
        ):
            result = invoke_structured_model(
                profile="label",
                prompt="prompt",
                payload={"x": 1},
                schema=StructuredOutput,
                config=ParserConfig(langfuse_enabled=True),
            )

        self.assertEqual(result.value, "ok")
        self.assertEqual(fake_model.structured.last_config, {"callbacks": ["cb"]})
        get_chat_model.assert_called_once_with(
            profile="label",
            model_override=None,
            timeout_seconds=180.0,
        )

    def test_run_parser_does_not_flush_langfuse_by_default(self) -> None:
        fake_result = WorkflowState(target_file=Path("sample.hwp"))
        fake_graph = FakeGraph(fake_result)
        with (
            patch("doc_processor.main.build_parser_graph", return_value=fake_graph),
            patch("doc_processor.main.langfuse_callback_context", _fake_langfuse_context),
            patch("doc_processor.main.flush_langfuse") as flush_langfuse,
        ):
            result = run_parser("sample.hwp")

        self.assertEqual(result.target_file, Path("sample.hwp"))
        flush_langfuse.assert_not_called()
        self.assertEqual(fake_graph.last_config, {"max_concurrency": 4})

    def test_run_parser_flushes_when_enabled(self) -> None:
        config = ParserConfig(langfuse_flush_at_end=True)
        fake_result = WorkflowState(target_file=Path("sample.hwp"), parser_config=config)
        fake_graph = FakeGraph(fake_result)
        with (
            patch("doc_processor.main.build_parser_graph", return_value=fake_graph),
            patch("doc_processor.main.langfuse_callback_context", _fake_langfuse_context),
            patch("doc_processor.main.flush_langfuse") as flush_langfuse,
        ):
            run_parser("sample.hwp", config=config)

        flush_langfuse.assert_called_once_with(config)


if __name__ == "__main__":
    unittest.main()
