from __future__ import annotations

from statistics import mean

from document_processor import DocIR, ParagraphIR

from ..parser_types import ParagraphAnalysis


def _required_node_id(paragraph: ParagraphIR) -> str:
    if paragraph.node_id:
        return paragraph.node_id
    raise ValueError("DocIR paragraph is missing node_id. Call DocIR.ensure_node_identity() before parsing.")


def build_paragraph_analyses(doc: DocIR) -> list[ParagraphAnalysis]:
    doc.ensure_node_identity()
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
        node_id=_required_node_id(paragraph),
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


def paragraph_position(paragraphs: list[ParagraphAnalysis], node_id: str) -> str:
    non_empty = non_empty_paragraphs(paragraphs)
    ids = [paragraph.node_id for paragraph in non_empty]
    if node_id not in ids:
        return "middle"
    if len(ids) == 1:
        return "only"
    index = ids.index(node_id)
    if index == 0:
        return "start"
    if index == len(ids) - 1:
        return "end"
    return "middle"


def paragraph_lookup(paragraphs: list[ParagraphAnalysis]) -> dict[str, ParagraphAnalysis]:
    return {paragraph.node_id: paragraph for paragraph in paragraphs}
