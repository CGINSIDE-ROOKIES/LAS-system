"""LLM parser/labeller graph for DocIR paragraphs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

try:
    from ..llm import get_chat_model, get_structured_method
    from ..processor_types import DocIR, ParagraphIR, ParagraphReviewResult, SourceType
    from ..prompts import load_prompt
    from .rules import apply_rule_labels
    from .utils import (
        build_neighbor_context,
        clear_inherited_context,
        iter_inherited_context_blocks,
        should_review_context_block,
    )
except ImportError:  # pragma: no cover - top-level import mode in local tests
    from llm import get_chat_model, get_structured_method
    from processor_types import DocIR, ParagraphIR, ParagraphReviewResult, SourceType
    from prompts import load_prompt
    from agent.rules import apply_rule_labels
    from agent.utils import (
        build_neighbor_context,
        clear_inherited_context,
        iter_inherited_context_blocks,
        should_review_context_block,
    )


def _state_get(state: Any, key: str, default: Any = None) -> Any:
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def _state_doc_ir(state: Any) -> DocIR:
    raw = _state_get(state, "doc_ir")
    if isinstance(raw, DocIR):
        return raw
    return DocIR.model_validate(raw)


def _state_parser_config(state: Any) -> ParserConfig:
    raw = _state_get(state, "parser_config")
    if isinstance(raw, ParserConfig):
        return raw
    if isinstance(raw, dict):
        return ParserConfig.model_validate(raw)
    return ParserConfig()


def _state_logger_name(state: Any) -> str | None:
    raw = _state_get(state, "logger_name")
    if isinstance(raw, str) and raw:
        return raw
    return None


def _get_logger(state: Any) -> logging.Logger | None:
    logger_name = _state_logger_name(state)
    if logger_name is None:
        return None
    return logging.getLogger(logger_name)


def _log(state: Any, message: str, *, level: str = "info") -> None:
    logger = _get_logger(state)
    if logger is None:
        return
    log_fn = getattr(logger, level, logger.info)
    log_fn(message)


def _json_for_log(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _serialize_payload(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump()
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _configure_run_logger(
    *,
    log_dir: str | None,
    log_to_console: bool,
    log_level: str,
) -> tuple[str | None, str | None]:
    if not log_dir and not log_to_console:
        return None, None

    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{run_stamp}_{uuid4().hex[:8]}"
    logger_name = f"doc_processor.parser.{run_id}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_file_path: str | None = None
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_dir:
        log_path = Path(log_dir).expanduser().resolve()
        log_path.mkdir(parents=True, exist_ok=True)
        file_path = log_path / f"parser_{run_id}.log"
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        log_file_path = str(file_path)

    return logger_name, log_file_path


def _close_run_logger(logger_name: str | None) -> None:
    if logger_name is None:
        return
    logger = logging.getLogger(logger_name)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _find_occurrence(text: str, needle: str, occurrence: int) -> int | None:
    if not needle:
        return None
    if occurrence <= 0:
        occurrence = 1

    start = 0
    seen = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            return None
        seen += 1
        if seen == occurrence:
            return idx
        start = idx + 1


class ParserConfig(BaseModel):
    llm_profile: str = "default"
    prompt_profile: str = "default"
    prompt_key: str = "paragraph_labeler"
    context_boundary_prompt_key: str = "clause_context_boundary"

    skip_empty: bool = True
    include_table_blocks: bool = True
    enable_rule_prelabel: bool = True
    enable_context_boundary_trim: bool = True
    enable_llm_warmup: bool = True
    context_neighbor_token_budget: int = 320
    structured_method: Literal["json_mode", "json_schema"] | None = "json_mode"
    log_dir: str | None = None
    log_to_console: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_llm_io: bool = False


class ContextBoundaryReviewResult(BaseModel):
    unit_id: str
    belongs_to_active_context: bool
    reason: str


_WORKER_PAYLOAD_PREAMBLE = (
    "Classify exactly one target paragraph. "
    "Treat only the JSON payload in the next message as the target input."
)
_BOUNDARY_PAYLOAD_PREAMBLE = (
    "Decide whether the target paragraph still belongs to the active inherited clause/subclause context. "
    "Treat only the JSON payload in the next message as the target input."
)


class ParserGraphState(BaseModel):
    doc_ir: DocIR
    parser_config: ParserConfig = Field(default_factory=ParserConfig)

    paragraph_idx: int | None = None

    # Runtime resources initialized once in graph.
    llm_model: Any | None = None
    prompt_text: str | None = None
    logger_name: str | None = None
    log_file_path: str | None = None

    # Indices resolved by rule-based pre-labeling (skip LLM).
    rule_resolved_indices: set[int] = Field(default_factory=set)

    paragraph_updates_temp: Annotated[
        list[tuple[int, ParagraphIR]],
        lambda left, right: [] if right == [] else left + right,
    ] = Field(default_factory=list)


def _prepare_runtime(state: ParserGraphState):
    cfg = _state_parser_config(state)
    updates: dict[str, Any] = {}
    if _state_get(state, "llm_model") is None:
        updates["llm_model"] = get_chat_model(profile=cfg.llm_profile)
    if _state_get(state, "prompt_text") is None:
        updates["prompt_text"] = load_prompt(
            cfg.prompt_key,
            profile=cfg.prompt_profile,
        )
    _log(
        state,
        (
            "runtime prepared "
            f"(llm_profile={cfg.llm_profile}, prompt_profile={cfg.prompt_profile}, "
            f"prompt_key={cfg.prompt_key})"
        ),
    )
    return updates


def _pre_label(state: ParserGraphState):
    """Apply deterministic rule-based labels before LLM processing."""
    cfg = _state_parser_config(state)
    if not cfg.enable_rule_prelabel:
        return {}
    doc_ir = _state_doc_ir(state)
    resolved, _unresolved = apply_rule_labels(doc_ir)
    _log(
        state,
        f"rule pre-label resolved {len(resolved)} paragraphs, {len(_unresolved)} remain for LLM",
    )
    return {
        "doc_ir": doc_ir,
        "rule_resolved_indices": set(resolved),
    }


def _splitter(state: ParserGraphState):
    doc_ir = _state_doc_ir(state)
    cfg = _state_parser_config(state)
    llm_model = _state_get(state, "llm_model")
    prompt_text = _state_get(state, "prompt_text")
    resolved = _state_get(state, "rule_resolved_indices") or set()
    sends: list[Send] = []
    for idx, paragraph in enumerate(doc_ir.paragraphs):
        if idx in resolved:
            continue
        if not cfg.include_table_blocks and paragraph.source_type == SourceType.TABLE_BLOCK:
            continue
        if cfg.skip_empty and not (paragraph.text or "").strip():
            continue
        sends.append(
            Send(
                "paragraph_worker",
                {
                    "paragraph_idx": idx,
                    "doc_ir": doc_ir,
                    "parser_config": cfg,
                    "llm_model": llm_model,
                    "prompt_text": prompt_text,
                    "logger_name": _state_logger_name(state),
                },
            )
        )

    _log(state, f"queued {len(sends)} paragraph workers")
    if not sends:
        return END
    return sends


def _warmup_llm(state: ParserGraphState):
    cfg = _state_parser_config(state)
    if not cfg.enable_llm_warmup:
        return {}

    doc_ir = _state_doc_ir(state)
    llm_model = _state_get(state, "llm_model")
    prompt_text = _state_get(state, "prompt_text")
    resolved = _state_get(state, "rule_resolved_indices") or set()
    if llm_model is None or prompt_text is None:
        return {}

    has_unresolved_work = any(
        idx not in resolved
        and (cfg.include_table_blocks or paragraph.source_type != SourceType.TABLE_BLOCK)
        and (not cfg.skip_empty or (paragraph.text or "").strip())
        for idx, paragraph in enumerate(doc_ir.paragraphs)
    )
    if not has_unresolved_work:
        _log(state, "llm warmup skipped (no unresolved paragraphs)")
        return {}

    warmup_payload = {
        "position": "only",
        "signals": {
            "clause_no": None,
            "subclause_no": None,
            "active_clause_no": None,
            "active_subclause_no": None,
            "centered": None,
            "font_size": None,
            "bold_ratio": None,
        },
        "unit_id": "_warmup",
        "prev": None,
        "next": None,
        "text": "워밍업용 더미 문단입니다.",
    }
    if cfg.structured_method is None:
        structured_llm = llm_model.with_structured_output(ParagraphReviewResult)
    else:
        structured_llm = llm_model.with_structured_output(
            ParagraphReviewResult,
            method=cfg.structured_method,
        )
    messages = [
        ("system", prompt_text),
        ("user", _WORKER_PAYLOAD_PREAMBLE),
        ("user", _serialize_payload(warmup_payload)),
    ]
    try:
        raw = structured_llm.invoke(messages)
        if cfg.log_llm_io:
            _log(state, f"llm warmup raw output\n{_json_for_log(raw)}")
        _log(state, "llm warmup complete")
    except Exception as exc:
        _log(state, f"llm warmup failed: {exc}", level="warning")
    return {}


def _compact_signals(paragraph: ParagraphIR) -> dict[str, Any]:
    """Flatten parser_signals to only the fields meaningful for LLM classification."""
    signals = paragraph.parser_signals
    if signals is None:
        return {
            "clause_no": None,
            "subclause_no": None,
            "active_clause_no": None,
            "active_subclause_no": None,
            "centered": None,
            "font_size": None,
            "bold_ratio": None,
        }
    return {
        "clause_no": signals.regex_clause.value if signals.regex_clause is not None else None,
        "subclause_no": (
            signals.regex_subclause.value if signals.regex_subclause is not None else None
        ),
        "active_clause_no": (
            signals.provisional_clause_no if signals.regex_clause is None else None
        ),
        "active_subclause_no": (
            signals.provisional_subclause_no if signals.regex_subclause is None else None
        ),
        "centered": True if signals.centered else None,
        "font_size": signals.font_size,
        "bold_ratio": round(signals.bold, 2) if signals.bold is not None else None,
    }


def _build_worker_payload(
    *,
    doc_ir: DocIR,
    parser_config: ParserConfig,
    model: Any,
    paragraph_idx: int,
) -> dict[str, Any]:
    paragraphs = doc_ir.paragraphs
    target = paragraphs[paragraph_idx]
    position, prev_text, next_text = build_neighbor_context(
        paragraphs,
        paragraph_idx=paragraph_idx,
        budget=max(0, parser_config.context_neighbor_token_budget),
        model=model,
    )

    payload: dict[str, Any] = {
        "position": position,
        "signals": _compact_signals(target),
        "unit_id": target.unit_id,
        "prev": prev_text,
        "next": next_text,
        "text": target.text,
    }
    return payload


_SPLIT_OP_ALIASES = {"split_clause", "split_paragraph", "split"}


def _normalize_raw_output(raw: Any) -> Any:
    """Fix known LLM op-value hallucinations before Pydantic validation."""
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return raw

    valid_op = "split_unit"
    normalized_ops = []
    for op in raw.get("ops") or []:
        if not isinstance(op, dict):
            continue
        op_val = op.get("op", "")
        if op_val == valid_op:
            normalized_op = dict(op)
        elif op_val in _SPLIT_OP_ALIASES:
            normalized_op = dict(op)
            normalized_op["op"] = valid_op
        # else: unknown op value (e.g. "add_label") — drop it
        else:
            continue

        normalized_ops.append(normalized_op)
    raw["ops"] = normalized_ops
    return raw


def _sanitize_result(
    result: ParagraphReviewResult,
    *,
    target_unit_id: str,
    target_text: str,
) -> ParagraphReviewResult | None:
    if result.unit_id != target_unit_id:
        return None

    safe_ops = []
    for op in result.ops:
        anchor_idx = _find_occurrence(target_text, op.anchor_text, op.occurrence)
        if anchor_idx is None:
            continue
        if anchor_idx <= 0 or anchor_idx >= len(target_text):
            continue
        safe_ops.append(op)

    return result.model_copy(update={"ops": safe_ops})


def _build_boundary_payload(
    *,
    doc_ir: DocIR,
    parser_config: ParserConfig,
    model: Any,
    paragraph_idx: int,
    block_start_idx: int,
    block_end_idx: int,
) -> dict[str, Any]:
    paragraphs = doc_ir.paragraphs
    target = paragraphs[paragraph_idx]
    signals = target.parser_signals
    _, prev_text, next_text = build_neighbor_context(
        paragraphs,
        paragraph_idx=paragraph_idx,
        budget=max(0, parser_config.context_neighbor_token_budget),
        model=model,
    )

    if block_start_idx == block_end_idx:
        position_in_block = "only"
    elif paragraph_idx == block_start_idx:
        position_in_block = "start"
    elif paragraph_idx == block_end_idx:
        position_in_block = "end"
    else:
        position_in_block = "middle"

    payload: dict[str, Any] = {
        "position_in_block": position_in_block,
        "active_clause_no": signals.provisional_clause_no,
        "active_subclause_no": signals.provisional_subclause_no,
        "paragraph_label": target.final_label,
        "unit_id": target.unit_id,
        "prev": prev_text,
        "next": next_text,
        "text": target.text,
    }
    return payload


def _trim_inherited_context_with_llm(
    doc_ir: DocIR,
    *,
    parser_config: ParserConfig,
    llm_model: Any,
    prompt_profile: str,
    logger_name: str | None,
) -> DocIR:
    if not parser_config.enable_context_boundary_trim:
        return doc_ir

    prompt_text = load_prompt(
        parser_config.context_boundary_prompt_key,
        profile=prompt_profile,
    )
    if parser_config.structured_method is None:
        structured_llm = llm_model.with_structured_output(ContextBoundaryReviewResult)
    else:
        structured_llm = llm_model.with_structured_output(
            ContextBoundaryReviewResult,
            method=parser_config.structured_method,
        )

    log_state = {"logger_name": logger_name}
    updated_doc = doc_ir.model_copy(deep=True)
    trimmed_ranges: list[str] = []

    for start_idx, end_idx in iter_inherited_context_blocks(updated_doc):
        if not should_review_context_block(updated_doc, start_idx, end_idx):
            continue

        clear_from: int | None = None
        for idx in range(end_idx, start_idx - 1, -1):
            paragraph = updated_doc.paragraphs[idx]
            if not (paragraph.text or "").strip():
                continue

            payload = _build_boundary_payload(
                doc_ir=updated_doc,
                parser_config=parser_config,
                model=llm_model,
                paragraph_idx=idx,
                block_start_idx=start_idx,
                block_end_idx=end_idx,
            )
            messages = [
                ("system", prompt_text),
                ("user", _BOUNDARY_PAYLOAD_PREAMBLE),
                ("user", _serialize_payload(payload)),
            ]
            if parser_config.log_llm_io:
                _log(
                    log_state,
                    (
                        f"context boundary input unit_id={paragraph.unit_id}\n"
                        f"system_prompt=\n{prompt_text}\n"
                        f"user_payload=\n{_json_for_log(payload)}"
                    ),
                )

            try:
                raw = structured_llm.invoke(messages)
                if parser_config.log_llm_io:
                    _log(
                        log_state,
                        f"context boundary raw output unit_id={paragraph.unit_id}\n{_json_for_log(raw)}",
                    )
                parsed = ContextBoundaryReviewResult.model_validate(raw)
            except Exception as exc:
                _log(
                    log_state,
                    f"context boundary error unit_id={paragraph.unit_id}: {exc}",
                    level="warning",
                )
                clear_from = None
                break

            if parsed.unit_id != paragraph.unit_id:
                _log(
                    log_state,
                    (
                        "context boundary dropped mismatched result "
                        f"expected={paragraph.unit_id} got={parsed.unit_id}"
                    ),
                    level="warning",
                )
                clear_from = None
                break

            if parser_config.log_llm_io:
                _log(
                    log_state,
                    f"context boundary parsed output unit_id={paragraph.unit_id}\n{_json_for_log(parsed)}",
                )

            if parsed.belongs_to_active_context:
                break

            clear_from = idx

        if clear_from is not None:
            clear_inherited_context(updated_doc, clear_from, end_idx)
            trimmed_ranges.append(
                f"{updated_doc.paragraphs[clear_from].unit_id}..{updated_doc.paragraphs[end_idx].unit_id}"
            )

    if trimmed_ranges:
        _log(log_state, f"context boundary trimmed {', '.join(trimmed_ranges)}")
    else:
        _log(log_state, "context boundary trimmed nothing")

    return updated_doc


def _paragraph_worker(state: ParserGraphState):
    idx = _state_get(state, "paragraph_idx")
    if idx is None:
        return {}
    doc_ir = _state_doc_ir(state)
    cfg = _state_parser_config(state)
    llm_model = _state_get(state, "llm_model")
    prompt_text = _state_get(state, "prompt_text")
    if llm_model is None or prompt_text is None:
        return {}
    if not (0 <= int(idx) < len(doc_ir.paragraphs)):
        return {}
    paragraph = doc_ir.paragraphs[int(idx)]
    _log(state, f"worker start idx={int(idx)} unit_id={paragraph.unit_id}")

    payload = _build_worker_payload(
        doc_ir=doc_ir,
        parser_config=cfg,
        model=llm_model,
        paragraph_idx=int(idx),
    )
    messages = [
        ("system", prompt_text),
        ("user", _WORKER_PAYLOAD_PREAMBLE),
        ("user", _serialize_payload(payload)),
    ]
    if cfg.log_llm_io:
        _log(
            state,
            (
                f"llm input unit_id={paragraph.unit_id}\n"
                f"system_prompt=\n{prompt_text}\n"
                f"user_payload=\n{_json_for_log(payload)}"
            ),
        )

    try:
        if cfg.structured_method is None:
            structured_llm = llm_model.with_structured_output(ParagraphReviewResult)
        else:
            structured_llm = llm_model.with_structured_output(
                ParagraphReviewResult,
                method=cfg.structured_method,
            )
        raw = structured_llm.invoke(messages)
        if cfg.log_llm_io:
            _log(
                state,
                f"llm raw output unit_id={paragraph.unit_id}\n{_json_for_log(raw)}",
            )
        normalized = _normalize_raw_output(raw)
        try:
            parsed = ParagraphReviewResult.model_validate(normalized)
        except Exception:
            # Fallback: salvage at least the label from the response
            if isinstance(normalized, dict) and normalized.get("label"):
                normalized["ops"] = []
                normalized["status"] = "ok"
                parsed = ParagraphReviewResult.model_validate(normalized)
                _log(
                    state,
                    f"worker fallback (label-only) unit_id={paragraph.unit_id}",
                    level="warning",
                )
            else:
                raise
        if cfg.log_llm_io:
            _log(
                state,
                f"llm parsed output unit_id={paragraph.unit_id}\n{_json_for_log(parsed)}",
            )
    except Exception as exc:
        _log(
            state,
            f"worker error idx={int(idx)} unit_id={paragraph.unit_id}: {exc}",
            level="error",
        )
        return {}

    safe = _sanitize_result(
        parsed,
        target_unit_id=paragraph.unit_id,
        target_text=paragraph.text,
    )
    if safe is None:
        _log(
            state,
            f"worker dropped mismatched result idx={int(idx)} unit_id={paragraph.unit_id}",
            level="warning",
        )
        return {}

    updated = paragraph.model_copy(deep=True)
    updated.apply_review_result(safe, strict=False)
    _log(
        state,
        (
            "worker done "
            f"idx={int(idx)} unit_id={paragraph.unit_id} "
            f"status={safe.status} label={safe.label}"
        ),
    )
    return {"paragraph_updates_temp": [(int(idx), updated)]}


def _reducer(state: ParserGraphState):
    pending_updates = _state_get(state, "paragraph_updates_temp", [])
    if not pending_updates:
        _log(state, "reducer received no updates")
        return {"paragraph_updates_temp": []}

    updated_doc = _state_doc_ir(state).model_copy(deep=True)
    updates = sorted(pending_updates, key=lambda x: x[0])
    for idx, paragraph in updates:
        if 0 <= idx < len(updated_doc.paragraphs):
            updated_doc.paragraphs[idx] = paragraph

    updated_doc.recompute_style_signals(include_table_runs=True)
    _log(state, f"reducer merged {len(updates)} paragraph updates")
    return {"doc_ir": updated_doc, "paragraph_updates_temp": []}


_builder = StateGraph(ParserGraphState)
_builder.add_node("prepare_runtime", _prepare_runtime)
_builder.add_node("pre_label", _pre_label)
_builder.add_node("warmup_llm", _warmup_llm)
_builder.add_node("paragraph_worker", _paragraph_worker)
_builder.add_node("reducer", _reducer)

_builder.add_edge(START, "prepare_runtime")
_builder.add_edge("prepare_runtime", "pre_label")
_builder.add_edge("pre_label", "warmup_llm")
_builder.add_conditional_edges("warmup_llm", _splitter, ["paragraph_worker", END])
_builder.add_edge("paragraph_worker", "reducer")
_builder.add_edge("reducer", END)

parser_graph = _builder.compile()


def run_parser(
    doc_ir: DocIR,
    *,
    max_concurrency: int = 4,
    llm_profile: str = "default",
    prompt_profile: str = "default",
    parser_config: ParserConfig | None = None,
    llm_model: Any | None = None,
    prompt_text: str | None = None,
    callbacks: list | None = None,
) -> DocIR:
    """Run parser subgraph and return updated DocIR."""
    cfg = parser_config.model_copy(deep=True) if parser_config is not None else ParserConfig()
    cfg.llm_profile = llm_profile
    cfg.prompt_profile = prompt_profile
    # Allow env-based override of structured_method.
    env_method = get_structured_method(profile=cfg.llm_profile)
    if env_method is not None:
        cfg.structured_method = env_method
    logger_name, log_file_path = _configure_run_logger(
        log_dir=cfg.log_dir,
        log_to_console=cfg.log_to_console,
        log_level=cfg.log_level,
    )

    state = ParserGraphState(
        doc_ir=doc_ir,
        parser_config=cfg,
        llm_model=llm_model,
        prompt_text=prompt_text,
        logger_name=logger_name,
        log_file_path=log_file_path,
    )
    _log(
        state,
        (
            "parser run start "
            f"(paragraphs={len(doc_ir.paragraphs)}, max_concurrency={max_concurrency}, "
            f"log_file={log_file_path})"
        ),
    )
    try:
        result = parser_graph.invoke(state, config={"max_concurrency": max_concurrency, "callbacks": callbacks or []})
        if isinstance(result, dict):
            out = result["doc_ir"]
        else:
            out = result.doc_ir
        runtime_llm_model = _state_get(result, "llm_model") if isinstance(result, dict) else result.llm_model
        if runtime_llm_model is None:
            runtime_llm_model = llm_model or get_chat_model(profile=cfg.llm_profile)
        out = _trim_inherited_context_with_llm(
            out,
            parser_config=cfg,
            llm_model=runtime_llm_model,
            prompt_profile=cfg.prompt_profile,
            logger_name=logger_name,
        )
        _log(state, "parser run complete")
        return out
    finally:
        _close_run_logger(logger_name)


__all__ = ["ParserConfig", "ParserGraphState", "parser_graph", "run_parser"]
