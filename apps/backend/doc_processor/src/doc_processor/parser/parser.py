from __future__ import annotations

from collections import Counter, defaultdict

from document_processor import DocIR

from ..parser_types import ClauseEntry, ParagraphAnalysis, ParagraphCategory, ParserAnalysis, SubclauseEntry, TextSpan, WorkflowMeta
from .rules import (
    NumberingMatch,
    SUBCLAUSE_RULE_PRIORITY,
    detect_clause_rule,
    iter_subclause_matches,
    match_clause_start,
    match_subclause_start,
)
from .selectors import build_paragraph_analyses, non_empty_paragraphs


def _detect_inline_subclause_rule(
    text: str,
    *,
    start_pos: int,
    allow_numeric_dot: bool,
) -> str | None:
    for rule_name in ("circled", "paren_numeric", "numeric_dot"):
        if rule_name == "numeric_dot" and not allow_numeric_dot:
            continue
        if any(iter_subclause_matches(text, rule_name=rule_name, start_pos=start_pos)):
            return rule_name
    return None


def _detect_global_subclause_rule(
    paragraphs: list[ParagraphAnalysis],
    *,
    clause_rule_name: str,
    allow_numeric_dot: bool,
) -> str | None:
    """Choose one document-level subclause rule from per-clause first-use evidence."""

    clause_local_rules: list[str] = []

    active_clause_seen = False
    clause_has_local_rule = False

    for paragraph in paragraphs:
        text = paragraph.text or ""
        if not text.strip():
            continue

        clause_match = match_clause_start(text, rule_name=clause_rule_name)
        if clause_match is not None:
            active_clause_seen = True
            clause_has_local_rule = False
            local_rule = _detect_inline_subclause_rule(
                text,
                start_pos=clause_match.end,
                allow_numeric_dot=allow_numeric_dot,
            )
            if local_rule is not None:
                clause_local_rules.append(local_rule)
                clause_has_local_rule = True
            continue

        if not active_clause_seen or clause_has_local_rule:
            continue

        first_sub_match = match_subclause_start(
            text,
            allow_numeric_dot=allow_numeric_dot,
        )
        if first_sub_match is None:
            continue

        clause_local_rules.append(first_sub_match.rule_name)
        clause_has_local_rule = True

    if not clause_local_rules:
        return None

    counts = Counter(clause_local_rules)
    return max(
        counts,
        key=lambda rule_name: (
            counts[rule_name],
            SUBCLAUSE_RULE_PRIORITY.get(rule_name, 0),
        ),
    )


def _make_span(
    text: str,
    *,
    start: int,
    end: int,
    kind: ParagraphCategory,
    clause_id: str | None,
    clause_no: str | None,
    subclause_id: str | None,
    subclause_no: str | None,
    source: str = "regex",
) -> TextSpan:
    return TextSpan(
        start=start,
        end=end,
        kind=kind,
        clause_id=clause_id,
        clause_no=clause_no,
        subclause_id=subclause_id,
        subclause_no=subclause_no,
        source=source,
        text=text[start:end],
    )


def _trimmed_end(text: str, end: int) -> int:
    while end > 0 and text[end - 1].isspace():
        end -= 1
    return end


def parse_document_structure(doc: DocIR) -> ParserAnalysis:
    paragraphs = build_paragraph_analyses(doc)
    non_empty = non_empty_paragraphs(paragraphs)
    clause_rule_name = detect_clause_rule(paragraph.text for paragraph in non_empty)
    analysis = ParserAnalysis(
        clause_rule_name=clause_rule_name,
        paragraphs=paragraphs,
    )

    if clause_rule_name is None:
        analysis.notes.append("No clause numbering rule found.")
        return analysis

    active_clause_id: str | None = None
    active_clause_no: str | None = None
    active_subclause_id: str | None = None
    active_subclause_no: str | None = None
    clause_counter = 0
    subclause_counters: dict[str, int] = defaultdict(int)

    allow_numeric_subclause = clause_rule_name != "numeric_dot"
    subclause_rule_name = _detect_global_subclause_rule(
        paragraphs,
        clause_rule_name=clause_rule_name,
        allow_numeric_dot=allow_numeric_subclause,
    )

    for paragraph in paragraphs:
        text = paragraph.text or ""
        if not text.strip():
            continue

        clause_match = match_clause_start(text, rule_name=clause_rule_name)
        spans: list[TextSpan] = []

        if clause_match is not None:
            clause_counter += 1
            active_clause_id = f"clause-{clause_counter}"
            active_clause_no = clause_match.number
            active_subclause_id = None
            active_subclause_no = None
            paragraph.clause_id = active_clause_id
            paragraph.clause_no = active_clause_no
            paragraph.clause_rule_name = clause_rule_name

            if subclause_rule_name is not None:
                sub_matches = list(
                    iter_subclause_matches(text, rule_name=subclause_rule_name, start_pos=clause_match.end)
                )
            else:
                sub_matches = []

            if sub_matches:
                first = sub_matches[0]
                clause_end = _trimmed_end(text, first.start)
                if clause_end > 0:
                    spans.append(
                        _make_span(
                            text,
                            start=0,
                            end=clause_end,
                            kind=ParagraphCategory.CLAUSE_HEADING,
                            clause_id=active_clause_id,
                            clause_no=active_clause_no,
                            subclause_id=None,
                            subclause_no=None,
                        )
                    )
                for index, sub_match in enumerate(sub_matches):
                    subclause_counters[active_clause_id] += 1
                    subclause_id = f"{active_clause_id}-subclause-{subclause_counters[active_clause_id]}"
                    next_start = sub_matches[index + 1].start if index + 1 < len(sub_matches) else len(text)
                    spans.append(
                        _make_span(
                            text,
                            start=sub_match.start,
                            end=_trimmed_end(text, next_start),
                            kind=ParagraphCategory.SUBCLAUSE_HEADING,
                            clause_id=active_clause_id,
                            clause_no=active_clause_no,
                            subclause_id=subclause_id,
                            subclause_no=sub_match.number,
                        )
                    )
                    active_subclause_id = subclause_id
                    active_subclause_no = sub_match.number
                paragraph.subclause_id = active_subclause_id
                paragraph.subclause_no = active_subclause_no
            else:
                spans.append(
                    _make_span(
                        text,
                        start=0,
                        end=len(text),
                        kind=ParagraphCategory.CLAUSE_HEADING,
                        clause_id=active_clause_id,
                        clause_no=active_clause_no,
                        subclause_id=None,
                        subclause_no=None,
                    )
                )

        else:
            if active_clause_id is None:
                paragraph.spans = []
                continue

            paragraph.clause_id = active_clause_id
            paragraph.clause_no = active_clause_no
            paragraph.clause_rule_name = clause_rule_name

            first_subclause_match = (
                match_subclause_start(
                    text,
                    rule_name=subclause_rule_name,
                    allow_numeric_dot=allow_numeric_subclause,
                )
                if subclause_rule_name is not None
                else None
            )

            if first_subclause_match is not None:
                sub_matches = list(iter_subclause_matches(text, rule_name=subclause_rule_name, start_pos=0))
                for index, sub_match in enumerate(sub_matches):
                    subclause_counters[active_clause_id] += 1
                    subclause_id = f"{active_clause_id}-subclause-{subclause_counters[active_clause_id]}"
                    next_start = sub_matches[index + 1].start if index + 1 < len(sub_matches) else len(text)
                    spans.append(
                        _make_span(
                            text,
                            start=sub_match.start,
                            end=_trimmed_end(text, next_start),
                            kind=ParagraphCategory.SUBCLAUSE_HEADING,
                            clause_id=active_clause_id,
                            clause_no=active_clause_no,
                            subclause_id=subclause_id,
                            subclause_no=sub_match.number,
                        )
                    )
                    active_subclause_id = subclause_id
                    active_subclause_no = sub_match.number
                paragraph.subclause_id = active_subclause_id
                paragraph.subclause_no = active_subclause_no
            else:
                inherited_kind = (
                    ParagraphCategory.SUBCLAUSE_BODY if active_subclause_id is not None else ParagraphCategory.CLAUSE_BODY
                )
                spans.append(
                    _make_span(
                        text,
                        start=0,
                        end=len(text),
                        kind=inherited_kind,
                        clause_id=active_clause_id,
                        clause_no=active_clause_no,
                        subclause_id=active_subclause_id,
                        subclause_no=active_subclause_no,
                    )
                )
                paragraph.subclause_id = active_subclause_id
                paragraph.subclause_no = active_subclause_no

        paragraph.spans = spans
        paragraph.subclause_rule_name = subclause_rule_name

    analysis.subclause_rule_name = subclause_rule_name
    analysis.clause_entries = build_clause_entries_from_analysis(analysis.paragraphs)
    return analysis


def build_clause_entries_from_analysis(paragraphs: list[ParagraphAnalysis]) -> list[ClauseEntry]:
    clause_order: list[str] = []
    by_clause: dict[str, ClauseEntry] = {}
    by_subclause: dict[tuple[str, str], int] = {}

    for paragraph in paragraphs:
        if not paragraph.clause_id or not paragraph.clause_no:
            continue

        if paragraph.clause_id not in by_clause:
            title = None
            for span in paragraph.spans:
                if span.kind == ParagraphCategory.CLAUSE_HEADING and span.text:
                    title = span.text.strip()
                    break
            by_clause[paragraph.clause_id] = ClauseEntry(
                clause_id=paragraph.clause_id,
                clause_no=paragraph.clause_no,
                title=title,
                heading_node_id=paragraph.node_id if any(span.kind == ParagraphCategory.CLAUSE_HEADING for span in paragraph.spans) else None,
                start_node_id=paragraph.node_id,
                end_node_id=paragraph.node_id,
                member_node_ids=[],
                spans_by_node={},
                subclauses=[],
            )
            clause_order.append(paragraph.clause_id)

        clause_entry = by_clause[paragraph.clause_id]
        clause_entry.end_node_id = paragraph.node_id
        clause_entry.member_node_ids.append(paragraph.node_id)
        if paragraph.spans:
            clause_entry.spans_by_node[paragraph.node_id] = paragraph.spans

        seen_in_para: set[str] = set()
        for span in paragraph.spans:
            if not span.subclause_id or not span.subclause_no or span.subclause_id in seen_in_para:
                continue
            seen_in_para.add(span.subclause_id)
            key = (paragraph.clause_id, span.subclause_id)
            if key not in by_subclause:
                clause_entry.subclauses.append(
                    SubclauseEntry(
                        subclause_id=span.subclause_id,
                        subclause_no=span.subclause_no,
                        start_node_id=paragraph.node_id,
                        end_node_id=paragraph.node_id,
                        member_node_ids=[paragraph.node_id],
                        spans_by_node={paragraph.node_id: [current for current in paragraph.spans if current.subclause_id == span.subclause_id]},
                    )
                )
                by_subclause[key] = len(clause_entry.subclauses) - 1
            else:
                subclause = clause_entry.subclauses[by_subclause[key]]
                subclause.end_node_id = paragraph.node_id
                if paragraph.node_id not in subclause.member_node_ids:
                    subclause.member_node_ids.append(paragraph.node_id)
                subclause.spans_by_node[paragraph.node_id] = [
                    current for current in paragraph.spans if current.subclause_id == span.subclause_id
                ]

    return [by_clause[clause_id] for clause_id in clause_order]
