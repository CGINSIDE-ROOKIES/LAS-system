from __future__ import annotations

from copy import deepcopy

from document_processor import DocIR, ParagraphIR

from ..types import (
    ClauseEntry,
    DocTargetRef,
    ParagraphCategory,
    Phase1Analysis,
    Phase1DocumentMeta,
    Phase1NodeMeta,
    WorkflowMeta,
)


def clause_entry_to_targets(entry: ClauseEntry) -> list[DocTargetRef]:
    return [DocTargetRef(unit_id=unit_id) for unit_id in entry.member_unit_ids]


def resolve_targets_to_paragraphs(
    doc: DocIR,
    targets: list[DocTargetRef],
) -> list[ParagraphIR]:
    by_unit = {paragraph.unit_id: paragraph for paragraph in doc.paragraphs}
    resolved: list[ParagraphIR] = []
    for target in targets:
        paragraph = by_unit.get(target.unit_id)
        if paragraph is not None:
            resolved.append(paragraph)
    return resolved


def resolve_clause_entry(
    doc: DocIR,
    entry: ClauseEntry,
) -> list[ParagraphIR]:
    return resolve_targets_to_paragraphs(doc, clause_entry_to_targets(entry))


def annotate_doc_with_phase1(
    doc: DocIR,
    analysis: Phase1Analysis,
) -> DocIR:
    annotated = doc.model_copy(deep=True)
    paragraph_map = {paragraph.unit_id: paragraph for paragraph in analysis.paragraphs}

    annotated.meta = _merge_meta(
        annotated.meta,
        phase1_doc=Phase1DocumentMeta(
            relevance=analysis.relevance,
            clause_rule_name=analysis.clause_rule_name,
            subclause_rule_name=analysis.subclause_rule_name,
            clause_entries=deepcopy(analysis.clause_entries),
            boundary_suspect_unit_ids=list(analysis.boundary_suspect_unit_ids),
            ambiguous_label_unit_ids=list(analysis.ambiguous_label_unit_ids),
            notes=list(analysis.notes),
        ),
    )

    for paragraph in annotated.paragraphs:
        current = paragraph_map.get(paragraph.unit_id)
        if current is None:
            continue
        paragraph.meta = _merge_meta(
            paragraph.meta,
            phase1=Phase1NodeMeta(
                category=current.category,
                clause_id=current.clause_id,
                clause_no=current.clause_no,
                subclause_id=current.subclause_id,
                subclause_no=current.subclause_no,
                clause_rule_name=current.clause_rule_name,
                subclause_rule_name=current.subclause_rule_name,
                spans=deepcopy(current.spans),
                candidate_labels=list(current.candidate_labels),
                boundary_suspect=current.boundary_suspect,
                split_suggestions=deepcopy(current.split_suggestions),
                notes=list(current.notes),
            ),
        )
        for table in paragraph.tables:
            table.meta = _merge_meta(
                table.meta,
                phase1=Phase1NodeMeta(
                    category=current.category,
                    clause_id=current.clause_id,
                    clause_no=current.clause_no,
                    subclause_id=current.subclause_id,
                    subclause_no=current.subclause_no,
                    clause_rule_name=current.clause_rule_name,
                    subclause_rule_name=current.subclause_rule_name,
                    boundary_suspect=current.boundary_suspect,
                    notes=["Inherited from owning paragraph during phase 1."],
                ),
            )
    return annotated


def _merge_meta(
    current: WorkflowMeta | None,
    *,
    phase1: Phase1NodeMeta | None = None,
    phase1_doc: Phase1DocumentMeta | None = None,
) -> WorkflowMeta:
    base = current.model_copy(deep=True) if current is not None else WorkflowMeta()
    if phase1 is not None:
        base.phase1 = phase1
    if phase1_doc is not None:
        base.phase1_doc = phase1_doc
    return base
