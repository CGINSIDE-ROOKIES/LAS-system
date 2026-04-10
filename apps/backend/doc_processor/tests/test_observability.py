from __future__ import annotations

import unittest
from unittest.mock import patch

from pydantic import BaseModel

from doc_processor.phase1.llm_utils import invoke_structured_model
from doc_processor.state import Phase1Config


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
    def test_invoke_structured_model_passes_langfuse_invoke_config(self) -> None:
        fake_model = FakeChatModel()
        with (
            patch("doc_processor.phase1.llm_utils.get_chat_model", return_value=fake_model),
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


if __name__ == "__main__":
    unittest.main()
