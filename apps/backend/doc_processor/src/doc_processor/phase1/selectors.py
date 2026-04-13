from __future__ import annotations

from statistics import mean

from document_processor import DocIR, ParagraphIR

from ..types import ParagraphAnalysis, WorkflowMeta


def build_paragraph_analyses(doc: DocIR) -> list[ParagraphAnalysis]:
    analyses: list[ParagraphAnalysis] = []
    for paragraph in doc.paragraphs:
        analyses.append(build_paragraph_analysis(paragraph))
    return analyses


def build_paragraph_analysis(paragraph: ParagraphIR) -> ParagraphAnalysis:
    run_sizes = [run.run_style.size_pt for run in paragraph.runs if run.run_style and run.run_style.size_pt]
    bold_runs = [run for run in paragraph.runs if run.run_style and run.run_style.bold]
    bold_ratio = None
    if paragraph.runs:
        bold_ratio = round(len(bold_runs) / max(len(paragraph.runs), 1), 4)

    return ParagraphAnalysis(
        unit_id=paragraph.unit_id,
        text=paragraph.text or "",
        page_number=paragraph.page_number,
        has_tables=bool(paragraph.tables),
        has_images=bool(paragraph.images),
        align=paragraph.para_style.align if paragraph.para_style else None,
        font_size_pt=round(mean(run_sizes), 2) if run_sizes else None,
        bold_ratio=bold_ratio,
    )


def non_empty_paragraphs(paragraphs: list[ParagraphAnalysis]) -> list[ParagraphAnalysis]:
    return [paragraph for paragraph in paragraphs if paragraph.text.strip()]


def paragraph_position(paragraphs: list[ParagraphAnalysis], unit_id: str) -> str:
    non_empty = non_empty_paragraphs(paragraphs)
    ids = [paragraph.unit_id for paragraph in non_empty]
    if unit_id not in ids:
        return "middle"
    if len(ids) == 1:
        return "only"
    index = ids.index(unit_id)
    if index == 0:
        return "start"
    if index == len(ids) - 1:
        return "end"
    return "middle"


def paragraph_lookup(paragraphs: list[ParagraphAnalysis]) -> dict[str, ParagraphAnalysis]:
    return {paragraph.unit_id: paragraph for paragraph in paragraphs}
