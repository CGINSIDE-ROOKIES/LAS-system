from __future__ import annotations

from pathlib import Path

from .logging_utils import log_info
from .observability import flush_langfuse, langfuse_callback_context
from .parser.graph import build_parser_graph
from .state import ParserConfig, WorkflowState


def run_parser(
    source: str | Path,
    *,
    config: ParserConfig | None = None,
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
        if invoke_config:
            result = graph.invoke(initial, config=invoke_config)
        else:
            result = graph.invoke(initial, config={"max_concurrency": initial.parser_config.max_concurrent_workers})
        validated = WorkflowState.model_validate(result)
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


__all__ = ["build_parser_graph", "run_parser"]
