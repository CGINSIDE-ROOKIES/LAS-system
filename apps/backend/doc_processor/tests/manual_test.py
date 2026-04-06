from __future__ import annotations

import sys
from pathlib import Path
import json

from dotenv import load_dotenv

THIS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = THIS_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

load_dotenv(PACKAGE_ROOT / ".env")

from langfuse import get_client
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

from processor_types import DocIR
from agent import ParserConfig, run_parser

test_dir = Path("/home/maxjo/Work/LAS-system/apps/backend/doc_processor/tests")
doc = DocIR.from_file("/home/maxjo/Work/LAS-system/apps/backend/doc_processor/tests/doc_samples/251029 2025년 3회 추경 사업설명서(평화협력국)_최종.hwpx"
)

with open(test_dir/"results/doc_base_test.json", "w+", encoding="utf-8") as f:
    json.dump(doc.model_dump(), f, indent=4, ensure_ascii=False)

print("base parse done.")

langfuse_handler = LangfuseCallbackHandler()

doc = run_parser(
    doc,
    parser_config=ParserConfig(
        log_dir=str(test_dir / "results/logs"),
        log_to_console=True,
        log_llm_io=True,
    ),
    callbacks=[langfuse_handler], # langfuse_handler
)

get_client().flush()

with open(test_dir/"results/doc_llm_test.json", "w+", encoding="utf-8") as f:
    json.dump(doc.model_dump(), f, indent=4, ensure_ascii=False)
