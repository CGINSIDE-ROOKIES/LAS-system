"""Minimal smoke test: does Langfuse receive a trace from a LangChain call?"""
from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from dotenv import load_dotenv
load_dotenv(PACKAGE_ROOT / ".env")

from langfuse import get_client
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
from llm import get_chat_model

handler = LangfuseCallbackHandler()
llm = get_chat_model()

resp = llm.invoke("Say 'hello' and nothing else.", config={"callbacks": [handler]})
print(f"LLM response: {resp.content}")

get_client().flush()
print("Flushed to Langfuse — check your dashboard.")
