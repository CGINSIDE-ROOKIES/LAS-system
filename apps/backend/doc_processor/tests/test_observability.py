from __future__ import annotations

import unittest
from unittest.mock import patch

from document_processor import DocIR
from pydantic import BaseModel

from doc_processor.observability.langfuse import _sanitize_langfuse_payload
from doc_processor.phase1.llm_utils import invoke_structured_model
from doc_processor.state import Phase1Config, WorkflowState


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


class ObservabilityTests(unittest.TestCase):
    def test_sanitize_langfuse_payload_redacts_docir_only(self) -> None:
        doc = DocIR.from_mapping({"s1.p1.r1": "표준계약서"})
        state = WorkflowState(
            base_doc=doc,
            working_doc=doc,
            phase1_config=Phase1Config(boundary_review_enabled=False, label_review_enabled=True),
        )

        payload = _sanitize_langfuse_payload({"state": state})
        sanitized_state = payload["state"]

        self.assertEqual(sanitized_state["base_doc"]["_excluded_type"], "DocIR")
        self.assertEqual(sanitized_state["base_doc"]["paragraph_count"], 1)
        self.assertNotIn("paragraphs", sanitized_state["base_doc"])
        self.assertEqual(sanitized_state["working_doc"]["_excluded_type"], "DocIR")
        self.assertFalse(sanitized_state["phase1_config"]["boundary_review_enabled"])
        self.assertTrue(sanitized_state["phase1_config"]["label_review_enabled"])

    def test_invoke_structured_model_passes_langfuse_invoke_config(self) -> None:
        fake_model = FakeChatModel()
        with (
            patch("doc_processor.phase1.llm_utils.get_chat_model", return_value=fake_model) as get_chat_model,
            patch("doc_processor.phase1.llm_utils.get_langchain_invoke_config", return_value={"callbacks": ["cb"]}),
        ):
            result = invoke_structured_model(
                profile="label",
                prompt="prompt",
                payload={"x": 1},
                schema=StructuredOutput,
                config=Phase1Config(langfuse_enabled=True),
            )

        self.assertEqual(result.value, "ok")
        self.assertEqual(fake_model.structured.last_config, {"callbacks": ["cb"]})
        get_chat_model.assert_called_once_with(
            profile="label",
            model_override=None,
            timeout_seconds=180.0,
        )


if __name__ == "__main__":
    unittest.main()
