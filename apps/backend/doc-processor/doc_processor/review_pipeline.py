"""
Review pipeline — top-level LangGraph graph for contract risk analysis.

Composes:
1. Document loading + style extraction
2. parser_graph (classification sub-graph)
3. Per-article risk analysis via Send() fan-out
4. HTML export with annotations

Usage::

    from doc_processor.review_pipeline import review_graph
    from doc_processor.las_types import ReviewState

    result = review_graph.invoke(
        ReviewState(target_file=Path("contract.hwpx")),
        config={"max_concurrency": 4},
    )
    html = result["html_output"]
"""

from pathlib import Path

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from doc_processor.las_types import (
    ReviewState, ArticleAnalysisState, DocumentState, ArticleAnnotations, ArticleRiskReport,
)
from doc_processor.parser import parser_graph
from doc_processor.risk_analyzer import risk_analysis_worker
from doc_processor.core.html_exporter import export_html
from doc_processor.core.style_extractor import extract_styles_hwpx, extract_styles_docx

###################################################################################################
# NODES
###################################################################################################

def load_document(state: ReviewState):
    """Parse document into IR and extract styles."""
    file_path = state.target_file
    print(f"\n=== LOAD DOCUMENT: {file_path.name} ===")

    # Parse into IR groups
    doc_state = DocumentState.from_file(file_path)
    ir_groups = doc_state.ir_groups
    print(f"  parsed {len(ir_groups)} IR groups")

    # Extract styles (need the live document object for HWPX)
    style_map = None
    match file_path.suffix:
        case ".hwpx":
            from hwpx import HwpxDocument
            with HwpxDocument.open(file_path) as doc:
                style_map = extract_styles_hwpx(doc)
        case ".hwp":
            # HWP is converted to HWPX internally by DocumentState.from_hwp
            # For styles, we'd need the converted HWPX — skip for now
            # (HTML export works without styles, just no formatting)
            print("  [warning] style extraction for HWP not yet supported, HTML will lack formatting")
        case ".docx":
            style_map = extract_styles_docx(file_path)

    return {"ir_groups": ir_groups, "style_map": style_map}


def run_parser(state: ReviewState):
    """Run the parser sub-graph to classify IR groups."""
    print(f"\n=== RUN PARSER ===")
    result = parser_graph.invoke(
        DocumentState(target_file=state.target_file, ir_groups=state.ir_groups),
        config={"max_concurrency": 4},
    )

    classified = result["ir_groups"]
    # Count categories
    cat_counts: dict[str, int] = {}
    for group in classified:
        for chunk in group.ir_chunks:
            cat_counts[chunk.category] = cat_counts.get(chunk.category, 0) + 1
    print(f"  classified chunks: {cat_counts}")

    return {"ir_groups": classified}


def fan_out_analysis(state: ReviewState):
    """Fan out risk analysis to 조문 articles via Send()."""
    sends = []
    for i, group in enumerate(state.ir_groups):
        if any(chunk.category == "조문" for chunk in group.ir_chunks):
            sends.append(Send("risk_analysis_worker", ArticleAnalysisState(
                group_idx=i, ir_group=group,
            )))

    print(f"\n=== FAN OUT ANALYSIS: {len(sends)} 조문 articles ===")

    if not sends:
        print("  no 조문 articles found, skipping analysis")
        return END
    return sends


def analysis_reducer(state: ReviewState):
    """Collect per-article results and build annotations dict."""
    print(f"\n=== ANALYSIS REDUCER: {len(state.analysis_temp)} results ===")

    sorted_results = sorted(state.analysis_temp, key=lambda x: x[0])
    annotations: dict[int, ArticleAnnotations] = {}
    risk_reports: list[ArticleRiskReport] = []

    for group_idx, report, annotation in sorted_results:
        if annotation.highlights:  # only add if there are highlights
            annotations[group_idx] = annotation
        risk_reports.append(report)

    total_risks = sum(len(r.risks) for r in risk_reports)
    print(f"  total risks: {total_risks}, articles with highlights: {len(annotations)}")

    return {
        "annotations": annotations,
        "risk_reports": risk_reports,
        "analysis_temp": [],  # clear collector
    }


def export_results(state: ReviewState):
    """Export annotated HTML."""
    print(f"\n=== EXPORT HTML ===")

    if state.style_map is None:
        # Create a minimal empty StyleMap for export
        from doc_processor.las_types import StyleMap
        style_map = StyleMap()
    else:
        style_map = state.style_map

    html = export_html(
        state.ir_groups,
        style_map,
        title=f"{state.target_file.stem} — 리스크 분석",
        annotations=state.annotations if state.annotations else None,
    )

    print(f"  HTML generated ({len(html)} chars)")
    return {"html_output": html}

###################################################################################################
# GRAPH
###################################################################################################

_builder = StateGraph(ReviewState)

_builder.add_node("load_document", load_document)
_builder.add_node("run_parser", run_parser)
_builder.add_node("risk_analysis_worker", risk_analysis_worker)
_builder.add_node("analysis_reducer", analysis_reducer)
_builder.add_node("export_results", export_results)

_builder.add_edge(START, "load_document")
_builder.add_edge("load_document", "run_parser")

_splitter_targets = ["risk_analysis_worker", END]
_builder.add_conditional_edges("run_parser", fan_out_analysis, _splitter_targets)

_builder.add_edge("risk_analysis_worker", "analysis_reducer")
_builder.add_edge("analysis_reducer", "export_results")
_builder.add_edge("export_results", END)

review_graph = _builder.compile()
