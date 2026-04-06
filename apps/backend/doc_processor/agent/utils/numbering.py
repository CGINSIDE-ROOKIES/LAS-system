from __future__ import annotations

try:
    from ...processor_types import DocIR
except ImportError:  # pragma: no cover - top-level import mode in local tests
    from processor_types import DocIR


def iter_inherited_context_blocks(doc_ir: DocIR) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    start_idx: int | None = None
    active_context: tuple[str | None, str | None] | None = None

    for idx, paragraph in enumerate(doc_ir.paragraphs):
        signals = paragraph.parser_signals
        has_direct_number = signals.regex_clause is not None or signals.regex_subclause is not None
        context = (signals.provisional_clause_no, signals.provisional_subclause_no)
        has_inherited_context = signals.provisional_clause_no is not None and not has_direct_number

        if not has_inherited_context:
            if start_idx is not None:
                blocks.append((start_idx, idx - 1))
                start_idx = None
                active_context = None
            continue

        if start_idx is None:
            start_idx = idx
            active_context = context
            continue

        if context != active_context:
            blocks.append((start_idx, idx - 1))
            start_idx = idx
            active_context = context

    if start_idx is not None:
        blocks.append((start_idx, len(doc_ir.paragraphs) - 1))

    return blocks


def should_review_context_block(doc_ir: DocIR, start_idx: int, end_idx: int) -> bool:
    last_non_empty_idx: int | None = None
    for idx in range(end_idx, start_idx - 1, -1):
        if (doc_ir.paragraphs[idx].text or "").strip():
            last_non_empty_idx = idx
            break

    if last_non_empty_idx is None:
        return False

    if end_idx == len(doc_ir.paragraphs) - 1:
        return True

    last_label = doc_ir.paragraphs[last_non_empty_idx].final_label
    return last_label not in {"body", "table_block", "table_cell"}


def clear_inherited_context(doc_ir: DocIR, start_idx: int, end_idx: int) -> None:
    for idx in range(start_idx, end_idx + 1):
        signals = doc_ir.paragraphs[idx].parser_signals
        if signals.regex_clause is None:
            signals.provisional_clause_no = None
        if signals.regex_subclause is None:
            signals.provisional_subclause_no = None
