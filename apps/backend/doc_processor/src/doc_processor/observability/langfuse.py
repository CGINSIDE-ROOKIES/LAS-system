from __future__ import annotations

import importlib.util
import os
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, Iterator

from document_processor import DocIR
from langgraph.types import Send
from pydantic import BaseModel

from ..env import ensure_local_env_loaded
from ..logging_utils import log_info
from ..state import WorkflowState
from ..types import ParserAnalysis, ParserResult

_CURRENT_INVOKE_CONFIG: ContextVar[dict[str, Any] | None] = ContextVar(
    "doc_processor_langfuse_invoke_config",
    default=None,
)

_SUMMARY_SAMPLE_LIMIT = 8


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


def _summarize_doc_ir(doc: DocIR) -> dict[str, Any]:
    return {
        "_excluded_type": "DocIR",
        "doc_id": doc.doc_id,
        "source_path": doc.source_path,
        "source_doc_type": doc.source_doc_type,
        "page_count": len(doc.pages),
        "paragraph_count": len(doc.paragraphs),
        "asset_count": len(doc.assets),
    }


def _summarize_string_list(items: list[Any], *, limit: int = _SUMMARY_SAMPLE_LIMIT) -> dict[str, Any]:
    sample = [str(item) for item in items[:limit]]
    return {
        "count": len(items),
        "sample": sample,
        "truncated": len(items) > limit,
    }


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _summarize_review_results(items: list[Any]) -> dict[str, Any]:
    unit_ids: list[str] = []
    statuses: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            unit_id = item.get("unit_id")
            if unit_id is not None:
                unit_ids.append(str(unit_id))
            review = item.get("review")
            if isinstance(review, Mapping):
                status = review.get("status") or review.get("action")
                if status is not None:
                    statuses.append(str(status))
    summary = _summarize_string_list(unit_ids)
    summary["statuses"] = _summarize_string_list(statuses)
    return summary


def _summarize_parser_analysis(analysis: ParserAnalysis) -> dict[str, Any]:
    paragraph_category_counts: dict[str, int] = {}
    for paragraph in analysis.paragraphs:
        if paragraph.category is None:
            continue
        key = paragraph.category.value
        paragraph_category_counts[key] = paragraph_category_counts.get(key, 0) + 1

    return {
        "_excluded_type": "ParserAnalysis",
        "relevance": _sanitize_langfuse_payload(analysis.relevance),
        "clause_rule_name": analysis.clause_rule_name,
        "subclause_rule_name": analysis.subclause_rule_name,
        "paragraph_count": len(analysis.paragraphs),
        "paragraph_category_counts": paragraph_category_counts,
        "clause_count": len(analysis.clause_entries),
        "boundary_suspect_unit_ids": _summarize_string_list(list(analysis.boundary_suspect_unit_ids)),
        "ambiguous_label_unit_ids": _summarize_string_list(list(analysis.ambiguous_label_unit_ids)),
        "notes": _summarize_string_list(list(analysis.notes)),
    }


def _summarize_parser_analysis_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    paragraphs = data.get("paragraphs")
    paragraph_count = len(paragraphs) if isinstance(paragraphs, list) else 0
    clause_entries = data.get("clause_entries")
    clause_count = len(clause_entries) if isinstance(clause_entries, list) else 0
    paragraph_category_counts: dict[str, int] = {}
    if isinstance(paragraphs, list):
        for paragraph in paragraphs:
            if not isinstance(paragraph, Mapping):
                continue
            category = paragraph.get("category")
            if category in {"", None}:
                continue
            key = str(category)
            paragraph_category_counts[key] = paragraph_category_counts.get(key, 0) + 1

    boundary_ids = data.get("boundary_suspect_unit_ids")
    ambiguous_ids = data.get("ambiguous_label_unit_ids")
    notes = data.get("notes")
    return {
        "_excluded_type": "ParserAnalysis",
        "relevance": _sanitize_langfuse_payload(data.get("relevance")),
        "clause_rule_name": data.get("clause_rule_name"),
        "subclause_rule_name": data.get("subclause_rule_name"),
        "paragraph_count": paragraph_count,
        "paragraph_category_counts": paragraph_category_counts,
        "clause_count": clause_count,
        "boundary_suspect_unit_ids": _summarize_string_list(list(boundary_ids) if isinstance(boundary_ids, list) else []),
        "ambiguous_label_unit_ids": _summarize_string_list(list(ambiguous_ids) if isinstance(ambiguous_ids, list) else []),
        "notes": _summarize_string_list(list(notes) if isinstance(notes, list) else []),
    }


def _summarize_parser_result(result: ParserResult) -> dict[str, Any]:
    return {
        "_excluded_type": "ParserResult",
        "accepted": result.accepted,
        "reason": result.reason,
        "relevance": _sanitize_langfuse_payload(result.relevance),
        "clause_rule_name": result.clause_rule_name,
        "subclause_rule_name": result.subclause_rule_name,
        "clause_count": result.clause_count,
        "subclause_count": result.subclause_count,
        "boundary_suspect_unit_ids": _summarize_string_list(list(result.boundary_suspect_unit_ids)),
        "ambiguous_label_unit_ids": _summarize_string_list(list(result.ambiguous_label_unit_ids)),
        "notes": _summarize_string_list(list(result.notes)),
    }


def _summarize_parser_result_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    boundary_ids = data.get("boundary_suspect_unit_ids")
    ambiguous_ids = data.get("ambiguous_label_unit_ids")
    notes = data.get("notes")
    return {
        "_excluded_type": "ParserResult",
        "accepted": data.get("accepted"),
        "reason": data.get("reason"),
        "relevance": _sanitize_langfuse_payload(data.get("relevance")),
        "clause_rule_name": data.get("clause_rule_name"),
        "subclause_rule_name": data.get("subclause_rule_name"),
        "clause_count": data.get("clause_count"),
        "subclause_count": data.get("subclause_count"),
        "boundary_suspect_unit_ids": _summarize_string_list(list(boundary_ids) if isinstance(boundary_ids, list) else []),
        "ambiguous_label_unit_ids": _summarize_string_list(list(ambiguous_ids) if isinstance(ambiguous_ids, list) else []),
        "notes": _summarize_string_list(list(notes) if isinstance(notes, list) else []),
    }


def _summarize_workflow_state(state: WorkflowState) -> dict[str, Any]:
    latest_delta = state.history[-1] if state.history else None
    return {
        "_excluded_type": "WorkflowState",
        "target_file": str(state.target_file) if state.target_file is not None else None,
        "base_doc": _sanitize_langfuse_payload(state.base_doc),
        "working_doc": _sanitize_langfuse_payload(state.working_doc),
        "parser_config": _sanitize_langfuse_payload(state.parser_config),
        "parser_analysis": _sanitize_langfuse_payload(state.parser_analysis),
        "parser_result": _sanitize_langfuse_payload(state.parser_result),
        "active_review_unit_id": state.active_review_unit_id,
        "active_review_kind": state.active_review_kind,
        "llm_review_stage": state.llm_review_stage,
        "boundary_review_results": _summarize_review_results(list(state.boundary_review_results)),
        "label_review_results": _summarize_review_results(list(state.label_review_results)),
        "current_version": state.current_version,
        "history_count": len(state.history),
        "latest_history": _sanitize_langfuse_payload(latest_delta),
        "errors": _summarize_string_list(list(state.errors)),
        "message_count": len(state.messages),
    }


def _summarize_workflow_state_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    history = data.get("history")
    latest_delta = history[-1] if isinstance(history, list) and history else None
    return {
        "_excluded_type": "WorkflowState",
        "target_file": str(data.get("target_file")) if data.get("target_file") is not None else None,
        "base_doc": _sanitize_langfuse_payload(data.get("base_doc")),
        "working_doc": _sanitize_langfuse_payload(data.get("working_doc")),
        "parser_config": _sanitize_langfuse_payload(data.get("parser_config")),
        "parser_analysis": _sanitize_langfuse_payload(data.get("parser_analysis")),
        "parser_result": _sanitize_langfuse_payload(data.get("parser_result")),
        "active_review_unit_id": data.get("active_review_unit_id"),
        "active_review_kind": data.get("active_review_kind"),
        "llm_review_stage": data.get("llm_review_stage"),
        "boundary_review_results": _summarize_review_results(_coerce_list(data.get("boundary_review_results"))),
        "label_review_results": _summarize_review_results(_coerce_list(data.get("label_review_results"))),
        "current_version": data.get("current_version"),
        "history_count": len(history) if isinstance(history, list) else 0,
        "latest_history": _sanitize_langfuse_payload(latest_delta),
        "errors": _summarize_string_list(_coerce_list(data.get("errors"))),
        "message_count": len(_coerce_list(data.get("messages"))),
    }


def _looks_like_workflow_state_mapping(value: Mapping[str, Any]) -> bool:
    return "parser_config" in value and any(
        key in value
        for key in ("working_doc", "base_doc", "parser_analysis", "parser_result", "target_file")
    )


def _looks_like_parser_analysis_mapping(value: Mapping[str, Any]) -> bool:
    return "paragraphs" in value and any(
        key in value for key in ("boundary_suspect_unit_ids", "ambiguous_label_unit_ids", "clause_entries")
    )


def _looks_like_parser_result_mapping(value: Mapping[str, Any]) -> bool:
    return "accepted" in value and "reason" in value and any(
        key in value for key in ("clause_count", "subclause_count", "boundary_suspect_unit_ids")
    )


def _sanitize_langfuse_payload(value: Any) -> Any:
    if isinstance(value, DocIR):
        return _summarize_doc_ir(value)
    if isinstance(value, WorkflowState):
        return _summarize_workflow_state(value)
    if isinstance(value, ParserAnalysis):
        return _summarize_parser_analysis(value)
    if isinstance(value, ParserResult):
        return _summarize_parser_result(value)
    if isinstance(value, Mapping):
        if _looks_like_workflow_state_mapping(value):
            return _summarize_workflow_state_mapping(value)
        if _looks_like_parser_analysis_mapping(value):
            return _summarize_parser_analysis_mapping(value)
        if _looks_like_parser_result_mapping(value):
            return _summarize_parser_result_mapping(value)
        return {key: _sanitize_langfuse_payload(item) for key, item in value.items()}
    if isinstance(value, BaseModel):
        data: dict[str, Any] = {}
        for field_name, field in value.__class__.model_fields.items():
            if field.exclude:
                continue
            data[field_name] = _sanitize_langfuse_payload(getattr(value, field_name))
        return data
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize_langfuse_payload(item) for item in value]
    return value


def _make_langfuse_callback_handler():
    from langfuse.langchain import CallbackHandler

    class SanitizingCallbackHandler(CallbackHandler):
        def on_chain_start(
            self,
            serialized,
            inputs,
            *,
            run_id,
            parent_run_id=None,
            tags=None,
            metadata=None,
            **kwargs,
        ):
            return super().on_chain_start(
                serialized,
                _sanitize_langfuse_payload(inputs),
                run_id=run_id,
                parent_run_id=parent_run_id,
                tags=tags,
                metadata=metadata,
                **kwargs,
            )

        def on_chain_end(
            self,
            outputs,
            *,
            run_id,
            parent_run_id=None,
            **kwargs,
        ):
            sanitized_kwargs = dict(kwargs)
            if "inputs" in sanitized_kwargs:
                sanitized_kwargs["inputs"] = _sanitize_langfuse_payload(sanitized_kwargs["inputs"])
            return super().on_chain_end(
                _sanitize_langfuse_payload(outputs),
                run_id=run_id,
                parent_run_id=parent_run_id,
                **sanitized_kwargs,
            )

        def on_chain_error(
            self,
            error,
            *,
            run_id,
            parent_run_id=None,
            tags=None,
            **kwargs,
        ):
            sanitized_kwargs = dict(kwargs)
            if "inputs" in sanitized_kwargs:
                sanitized_kwargs["inputs"] = _sanitize_langfuse_payload(sanitized_kwargs["inputs"])
            return super().on_chain_error(
                error,
                run_id=run_id,
                parent_run_id=parent_run_id,
                tags=tags,
                **sanitized_kwargs,
            )

    return SanitizingCallbackHandler()


@contextmanager
def langfuse_callback_context(
    config: Any | None,
    *,
    source: str,
) -> Iterator[dict[str, Any]]:
    if not langfuse_enabled(config):
        yield {}
        return

    from langfuse import propagate_attributes

    trace_name = getattr(config, "langfuse_trace_name", "doc_processor.structure_analysis")
    metadata = _string_metadata(config, {"component": "doc_processor", "phase": "structure_analysis", "source": source})
    invoke_config: dict[str, Any] = {"callbacks": [_make_langfuse_callback_handler()], "run_name": trace_name}
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
        current = {"callbacks": [_make_langfuse_callback_handler()]}

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


def traced_structure_analysis_node(name: str):
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
            config = getattr(state, "parser_config", None)
            log_info(config, "[%s] start", name)
            result = fn(state, *args, **kwargs)
            goto = getattr(result, "goto", None)
            log_info(config, "[%s] done goto=%s", name, _summarize_goto(goto))
            return result

        return wrapper

    return decorator


traced_parser_node = traced_structure_analysis_node
