from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .logging_utils import log_info
from .observability import flush_langfuse, langfuse_callback_context
from .parser.graph import build_parser_graph
from .state import ParserConfig, WorkflowState

ParserProgressCallback = Callable[[dict[str, Any]], None]


def run_parser(
    source: str | Path,
    *,
    config: ParserConfig | None = None,
    progress_callback: ParserProgressCallback | None = None,
) -> WorkflowState:
    graph = build_parser_graph()
    resolved_config = config or ParserConfig()
    initial = WorkflowState(target_file=Path(source), parser_config=resolved_config)
    log_info(initial.parser_config, "structure analysis run start source=%s", initial.target_file)
    with langfuse_callback_context(
        initial.parser_config,
        source=str(initial.target_file),
    ) as invoke_config:
        if invoke_config:
            invoke_config = dict(invoke_config)
            invoke_config["max_concurrency"] = initial.parser_config.max_concurrent_workers
        run_config = invoke_config or {"max_concurrency": initial.parser_config.max_concurrent_workers}
        if progress_callback is None:
            result = graph.invoke(initial, config=run_config)
            validated = WorkflowState.model_validate(result)
        else:
            progress_state: dict[str, Any] = {"label_total": None, "label_done": 0}
            latest_values: dict[str, Any] | None = None
            for mode, chunk in graph.stream(
                initial,
                config=run_config,
                stream_mode=["updates", "values"],
            ):
                if mode == "updates":
                    _emit_parser_progress_from_update(progress_callback, progress_state, chunk)
                elif mode == "values":
                    latest_values = chunk
            if latest_values is None:
                raise ValueError("Parser stream did not produce a final state.")
            validated = WorkflowState.model_validate(latest_values)
    if initial.parser_config.langfuse_flush_at_end:
        flush_langfuse(initial.parser_config)
    if validated.parser_result is not None:
        log_info(
            initial.parser_config,
            "structure analysis run done accepted=%s clauses=%s subclauses=%s",
            validated.parser_result.accepted,
            validated.parser_result.clause_count,
            validated.parser_result.subclause_count,
        )
    return validated


def _emit_parser_progress_from_update(
    callback: ParserProgressCallback,
    progress_state: dict[str, Any],
    chunk: dict[str, Any],
) -> None:
    if "load_document" in chunk:
        callback({"phase": "load_document", "progress": 0.10})
    if "screen_relevance" in chunk:
        callback({"phase": "screen_relevance", "progress": 0.20})
    if "regex_analysis" in chunk:
        callback({"phase": "regex_analysis", "progress": 0.35})

    llm_update = chunk.get("llm_analysis")
    if isinstance(llm_update, dict):
        stage = llm_update.get("llm_review_stage")
        analysis = llm_update.get("parser_analysis")
        if stage == "boundary":
            callback(
                {
                    "phase": "boundary_review_started",
                    "progress": 0.40,
                    "total": _analysis_list_len(analysis, "boundary_suspect_node_ids"),
                }
            )
        elif stage == "label":
            total = _analysis_list_len(analysis, "ambiguous_label_node_ids")
            progress_state["label_total"] = total
            progress_state["label_done"] = 0
            callback({"phase": "label_review_started", "progress": 0.70, "total": total})
        elif stage is None:
            callback({"phase": "llm_analysis_completed", "progress": 0.90})

    boundary_update = chunk.get("boundary_llm_batch")
    if isinstance(boundary_update, dict):
        results = boundary_update.get("boundary_review_results") or []
        callback(
            {
                "phase": "boundary_review_completed",
                "progress": 0.65,
                "processed": len(results),
            }
        )

    worker_update = chunk.get("llm_analysis_worker")
    if isinstance(worker_update, dict):
        results = worker_update.get("label_review_results") or []
        if results:
            progress_state["label_done"] = int(progress_state.get("label_done") or 0) + len(results)
            total = int(progress_state.get("label_total") or progress_state["label_done"])
            done = int(progress_state["label_done"])
            progress = 0.70 + (0.20 * min(done, total) / max(total, 1))
            callback(
                {
                    "phase": "label_review_progress",
                    "progress": progress,
                    "processed": done,
                    "total": total,
                    "node_id": results[-1].get("node_id") if isinstance(results[-1], dict) else None,
                }
            )

    if "finalize_llm" in chunk:
        callback({"phase": "finalize", "progress": 1.0})


def _analysis_list_len(analysis: Any, field_name: str) -> int:
    if isinstance(analysis, dict):
        value = analysis.get(field_name)
    else:
        value = getattr(analysis, field_name, None)
    return len(value or [])


__all__ = ["ParserProgressCallback", "build_parser_graph", "run_parser"]
