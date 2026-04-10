from __future__ import annotations

import importlib.util
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Iterator

from langgraph.types import Send

from ..env import ensure_local_env_loaded
from ..logging_utils import log_info

_CURRENT_INVOKE_CONFIG: ContextVar[dict[str, Any] | None] = ContextVar(
    "doc_processor_langfuse_invoke_config",
    default=None,
)


def _langfuse_sdk_available() -> bool:
    return importlib.util.find_spec("langfuse") is not None


def _langchain_sdk_available() -> bool:
    return importlib.util.find_spec("langchain") is not None


def _langfuse_configured() -> bool:
    ensure_local_env_loaded()
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def langfuse_enabled(config: Any | None) -> bool:
    explicit = getattr(config, "langfuse_enabled", None)
    if explicit is False:
        return False
    if explicit is True:
        if not _langfuse_sdk_available():
            raise RuntimeError("Langfuse is enabled but the 'langfuse' package is not installed.")
        if not _langchain_sdk_available():
            raise RuntimeError("Langfuse callback tracing requires the 'langchain' package to be installed.")
        if not _langfuse_configured():
            raise RuntimeError(
                "Langfuse is enabled but LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not configured."
            )
        return True
    return _langfuse_sdk_available() and _langchain_sdk_available() and _langfuse_configured()


def _string_metadata(config: Any | None, metadata: dict[str, Any] | None = None) -> dict[str, str] | None:
    merged: dict[str, Any] = {}
    config_metadata = getattr(config, "langfuse_metadata", None) or {}
    merged.update(config_metadata)
    if metadata:
        merged.update(metadata)
    if not merged:
        return None
    return {key: str(value) for key, value in merged.items()}


@contextmanager
def langfuse_callback_context(
    config: Any | None,
    *,
    source: str,
    input_payload: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    if not langfuse_enabled(config):
        yield {}
        return

    from langfuse import propagate_attributes
    from langfuse.langchain import CallbackHandler

    trace_name = getattr(config, "langfuse_trace_name", "doc_processor.phase1")
    metadata = _string_metadata(config, {"component": "doc_processor", "phase": "phase1", "source": source})
    invoke_config: dict[str, Any] = {"callbacks": [CallbackHandler()], "run_name": trace_name}
    if metadata:
        invoke_config["metadata"] = metadata
    tags = getattr(config, "langfuse_tags", None)
    if tags:
        invoke_config["tags"] = list(tags)

    with propagate_attributes(
        trace_name=trace_name,
        user_id=getattr(config, "langfuse_user_id", None),
        session_id=getattr(config, "langfuse_session_id", None),
        tags=tags,
        metadata=metadata,
    ):
        token = _CURRENT_INVOKE_CONFIG.set(invoke_config)
        try:
            yield invoke_config
        finally:
            _CURRENT_INVOKE_CONFIG.reset(token)


def get_langchain_invoke_config(config: Any | None, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    current = _CURRENT_INVOKE_CONFIG.get()
    if current is None:
        if not langfuse_enabled(config):
            return {}
        from langfuse.langchain import CallbackHandler

        current = {"callbacks": [CallbackHandler()]}

    invoke_config = dict(current)
    base_metadata = dict(invoke_config.get("metadata") or {})
    extra_metadata = _string_metadata(config, metadata)
    if extra_metadata:
        base_metadata.update(extra_metadata)
    if base_metadata:
        invoke_config["metadata"] = base_metadata
    return invoke_config


def flush_langfuse(config: Any | None) -> None:
    if not langfuse_enabled(config):
        return
    from langfuse import get_client

    get_client().flush()


def traced_phase1_node(name: str):
    def _summarize_goto(goto: Any) -> Any:
        if isinstance(goto, Send):
            return f"Send({goto.node})"
        if isinstance(goto, (list, tuple)) and goto and all(isinstance(item, Send) for item in goto):
            node_names = sorted({item.node for item in goto})
            return f"{len(goto)} sends -> {','.join(node_names)}"
        return goto

    def decorator(fn):
        @wraps(fn)
        def wrapper(state, *args, **kwargs):
            config = getattr(state, "phase1_config", None)
            log_info(config, "[%s] start", name)
            result = fn(state, *args, **kwargs)
            goto = getattr(result, "goto", None)
            log_info(config, "[%s] done goto=%s", name, _summarize_goto(goto))
            return result

        return wrapper

    return decorator
