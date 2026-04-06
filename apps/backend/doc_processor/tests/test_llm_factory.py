from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

THIS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = THIS_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

factory = importlib.import_module("llm.factory")


class DotenvFactoryTests(unittest.TestCase):
    def test_load_local_dotenv_reads_package_env_without_override(self) -> None:
        calls: list[tuple[Path, bool]] = []

        def fake_load_dotenv(path: Path, override: bool = False) -> bool:
            calls.append((Path(path), override))
            return True

        original_loader = factory.load_dotenv
        original_flag = factory._DOTENV_LOADED
        try:
            factory.load_dotenv = fake_load_dotenv
            factory._DOTENV_LOADED = False
            factory._load_local_dotenv()
        finally:
            factory.load_dotenv = original_loader
            factory._DOTENV_LOADED = original_flag

        self.assertTrue(calls)
        self.assertEqual(calls[0][0], PACKAGE_ROOT / ".env")
        self.assertFalse(calls[0][1])

    def test_get_chat_model_supports_gemini_provider(self) -> None:
        fake_module = types.ModuleType("langchain_google_genai")

        class FakeGemini:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_module.ChatGoogleGenerativeAI = FakeGemini

        with (
            patch.dict(
                os.environ,
                {
                    "DOC_PROCESSOR_LLM_PROVIDER": "gemini",
                    "DOC_PROCESSOR_LLM_MODEL": "gemini-2.5-flash",
                    "DOC_PROCESSOR_LLM_API_KEY": "test-key",
                },
                clear=False,
            ),
            patch.dict(sys.modules, {"langchain_google_genai": fake_module}),
        ):
            model = factory.get_chat_model()

        self.assertIsInstance(model, FakeGemini)
        self.assertEqual(model.kwargs["model"], "gemini-2.5-flash")
        self.assertEqual(model.kwargs["google_api_key"], "test-key")


if __name__ == "__main__":
    unittest.main()
