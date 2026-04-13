from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from doc_processor.env import _load_simple_env_file


class EnvLoadingTests(unittest.TestCase):
    def test_simple_env_loader_populates_missing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "LANGFUSE_PUBLIC_KEY=pk-test\n"
                "LANGFUSE_SECRET_KEY=sk-test\n"
                "DOC_PROCESSOR_LLM_MODEL=gpt-test\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                _load_simple_env_file(env_path)
                self.assertEqual(os.environ["LANGFUSE_PUBLIC_KEY"], "pk-test")
                self.assertEqual(os.environ["LANGFUSE_SECRET_KEY"], "sk-test")
                self.assertEqual(os.environ["DOC_PROCESSOR_LLM_MODEL"], "gpt-test")


if __name__ == "__main__":
    unittest.main()
