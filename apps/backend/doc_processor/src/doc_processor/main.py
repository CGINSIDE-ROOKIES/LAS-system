from __future__ import annotations

from pathlib import Path

from .logging_utils import log_info
from .observability import flush_langfuse, langfuse_callback_context
from .phase1.graph import build_phase1_graph
from .state import Phase1Config, WorkflowState


def run_phase1(
    source: str | Path,
    *,
    config: Phase1Config | None = None,
) -> WorkflowState:
    graph = build_phase1_graph()
    resolved_config = config or Phase1Config()
    initial = WorkflowState(target_file=Path(source), phase1_config=resolved_config)
    log_info(initial.phase1_config, "structure analysis run start source=%s", initial.target_file)
    with langfuse_callback_context(
        initial.phase1_config,
        source=str(initial.target_file),
    ) as invoke_config:
        if invoke_config:
            invoke_config = dict(invoke_config)
            invoke_config["max_concurrency"] = initial.phase1_config.max_concurrent_workers
        if invoke_config:
            result = graph.invoke(initial, config=invoke_config)
        else:
            result = graph.invoke(initial, config={"max_concurrency": initial.phase1_config.max_concurrent_workers})
        validated = WorkflowState.model_validate(result)
    if initial.phase1_config.langfuse_flush_at_end:
        flush_langfuse(initial.phase1_config)
    if validated.phase1_result is not None:
        log_info(
            initial.phase1_config,
            "structure analysis run done accepted=%s clauses=%s subclauses=%s",
            validated.phase1_result.accepted,
            validated.phase1_result.clause_count,
            validated.phase1_result.subclause_count,
        )
    return validated


__all__ = ["build_phase1_graph", "run_phase1"]
