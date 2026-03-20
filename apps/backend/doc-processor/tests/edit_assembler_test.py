"""
edit_assembler round-trip test
==============================

Tests the pipeline:
  document (docx / hwpx) → IR → [edit_assembler] → export HTML + save document

For each test document:
  1. Parse into IR + extract styles
  2. Export "before" HTML
  3. Simulate LLM edits on formatted_str (word replacements, insertions, deletions)
  4. Apply edits via edit_assembler.apply_edit()
  5. Export "after" HTML
  6. Save edited document to results/

Results go to tests/results/ for manual visual inspection.
"""

import sys
import shutil
from pathlib import Path

# Ensure the package root is importable
PKG_ROOT = Path(__file__).resolve().parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from doc_processor.core.ir import create_ir_dict, create_ir_dict_from_mapping, ir_grouper
from doc_processor.core.docx_ir import export_docx_structured
from doc_processor.core.style_extractor import extract_styles_hwpx, extract_styles_docx
from doc_processor.core.html_exporter import export_html
from doc_processor.core.edit_assembler import apply_edit

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

SAMPLES_DIR = Path(__file__).resolve().parent / "doc_samples"


# ---------------------------------------------------------------------------
# Edit simulation helpers
# ---------------------------------------------------------------------------

def simulate_edits(article: "IRGroup") -> str | None:
    """Apply realistic LLM-style edits *within* run spans of formatted_str.

    We collect all edits as (abs_start, abs_end, replacement) first, then
    apply them from back to front so earlier positions stay valid.

    Returns the edited string, or None if no editable runs exist.
    """
    import re

    text = article.formatted_str
    spans = article.run_spans()
    if not spans or len(text) < 20:
        return None

    # Collect edits as (start, end, replacement) — apply back-to-front later
    edits: list[tuple[int, int, str]] = []

    # Edit 1: Find a run containing '다.' and insert '(수정)' before the dot
    for span in spans:
        run_text = text[span.start:span.end]
        m = re.search(r"다\.", run_text)
        if m:
            pos = span.start + m.start() + 1  # after '다', before '.'
            edits.append((pos, pos, "(수정)"))
            break

    # Edit 2: Find a run with a 2+ char Korean word and replace it
    used_spans = {e_span for e in edits for e_span in [e[0]]}
    for span in spans:
        if span.start in used_spans:
            continue
        run_text = text[span.start:span.end]
        m = re.search(r"[가-힣]{2,4}", run_text)
        if m and m.group(0) not in ("수정",):
            word = m.group(0)
            abs_s = span.start + m.start()
            abs_e = span.start + m.end()
            edits.append((abs_s, abs_e, f"[{word} → 변경됨]"))
            break

    # Edit 3: Append text at the exact end of the last non-empty run
    #   (tests the boundary insert fix in _clip_run_spans)
    for span in reversed(spans):
        run_text = text[span.start:span.end]
        if run_text.strip():
            edits.append((span.end, span.end, " [추가 문구]"))
            break

    if not edits:
        return None

    # Apply edits back-to-front to preserve positions
    edits.sort(key=lambda e: e[0], reverse=True)
    for start, end, replacement in edits:
        text = text[:start] + replacement + text[end:]

    return text


# ---------------------------------------------------------------------------
# HWPX test
# ---------------------------------------------------------------------------

def test_hwpx(hwpx_path: Path):
    from hwpx import HwpxDocument

    stem = hwpx_path.stem
    print(f"\n{'='*60}")
    print(f"HWPX TEST: {stem}")
    print(f"{'='*60}")

    with HwpxDocument.open(hwpx_path) as doc:
        # 1. Parse IR
        ir_dict = create_ir_dict(doc)
        ir_groups = ir_grouper(ir_dict)
        style_map = extract_styles_hwpx(doc)

        print(f"  IR groups: {len(ir_groups)}")
        for i, grp in enumerate(ir_groups):
            print(f"    [{i}] article={grp.article_n}, chunks={len(grp.ir_chunks)}, "
                  f"len(formatted)={len(grp.formatted_str)}")

        # 2. Export "before" HTML
        html_before = export_html(ir_groups, style_map, title=f"{stem} (before edit)")
        before_path = RESULTS_DIR / f"{stem}_before.html"
        before_path.write_text(html_before, encoding="utf-8")
        print(f"  -> {before_path.name}")

        # 3. Apply edits to each group
        edit_results = []
        for idx, grp in enumerate(ir_groups):
            edited = simulate_edits(grp)
            if edited is None:
                continue
            result = apply_edit(grp, edited, doc)
            edit_results.append((idx, result))
            print(f"  Edit group[{idx}]: opcodes={result.opcodes_total}, "
                  f"applied={result.opcodes_applied}, "
                  f"runs_modified={result.runs_modified[:5]}{'...' if len(result.runs_modified) > 5 else ''}")
            if result.warnings:
                for w in result.warnings:
                    print(f"    WARNING: {w}")
            if result.skipped_table_spans:
                print(f"    Skipped tables: {result.skipped_table_spans}")

        # 4. Re-parse IR from the now-modified document to get updated text
        ir_dict_after = create_ir_dict(doc)
        ir_groups_after = ir_grouper(ir_dict_after)
        style_map_after = extract_styles_hwpx(doc)

        # 5. Export "after" HTML
        html_after = export_html(ir_groups_after, style_map_after, title=f"{stem} (after edit)")
        after_path = RESULTS_DIR / f"{stem}_after.html"
        after_path.write_text(html_after, encoding="utf-8")
        print(f"  -> {after_path.name}")

        # 6. Save edited document
        out_doc_path = RESULTS_DIR / f"{stem}_edited.hwpx"
        doc.save_to_path(str(out_doc_path))
        print(f"  -> {out_doc_path.name}")

    return edit_results


# ---------------------------------------------------------------------------
# DOCX test
# ---------------------------------------------------------------------------

def test_docx(docx_path: Path):
    from docx import Document as DocxDocument

    stem = docx_path.stem
    print(f"\n{'='*60}")
    print(f"DOCX TEST: {stem}")
    print(f"{'='*60}")

    # 1. Parse IR
    parsed = export_docx_structured(docx_path)
    ir_dict = create_ir_dict_from_mapping(parsed)
    ir_groups = ir_grouper(ir_dict)
    style_map = extract_styles_docx(docx_path)

    print(f"  IR groups: {len(ir_groups)}")
    for i, grp in enumerate(ir_groups):
        print(f"    [{i}] article={grp.article_n}, chunks={len(grp.ir_chunks)}, "
              f"len(formatted)={len(grp.formatted_str)}")

    # 2. Export "before" HTML
    html_before = export_html(ir_groups, style_map, title=f"{stem} (before edit)")
    before_path = RESULTS_DIR / f"{stem}_before.html"
    before_path.write_text(html_before, encoding="utf-8")
    print(f"  -> {before_path.name}")

    # 3. Open the actual docx for editing, re-parse IR from same doc object
    #    (edit_assembler needs the live doc to write into)
    doc = DocxDocument(str(docx_path))
    # Re-parse so IR chunk IDs align with this doc instance
    parsed2 = export_docx_structured(docx_path)
    ir_dict2 = create_ir_dict_from_mapping(parsed2)
    ir_groups2 = ir_grouper(ir_dict2)

    # 4. Apply edits
    edit_results = []
    for idx, grp in enumerate(ir_groups2):
        edited = simulate_edits(grp)
        if edited is None:
            continue
        result = apply_edit(grp, edited, doc)
        edit_results.append((idx, result))
        print(f"  Edit group[{idx}]: opcodes={result.opcodes_total}, "
              f"applied={result.opcodes_applied}, "
              f"runs_modified={result.runs_modified[:5]}{'...' if len(result.runs_modified) > 5 else ''}")
        if result.warnings:
            for w in result.warnings:
                print(f"    WARNING: {w}")
        if result.skipped_table_spans:
            print(f"    Skipped tables: {result.skipped_table_spans}")

    # 5. Save edited document
    out_doc_path = RESULTS_DIR / f"{stem}_edited.docx"
    doc.save(str(out_doc_path))
    print(f"  -> {out_doc_path.name}")

    # 6. Re-parse edited doc for "after" HTML
    parsed_after = export_docx_structured(out_doc_path)
    ir_dict_after = create_ir_dict_from_mapping(parsed_after)
    ir_groups_after = ir_grouper(ir_dict_after)
    style_map_after = extract_styles_docx(out_doc_path)

    html_after = export_html(ir_groups_after, style_map_after, title=f"{stem} (after edit)")
    after_path = RESULTS_DIR / f"{stem}_after.html"
    after_path.write_text(html_after, encoding="utf-8")
    print(f"  -> {after_path.name}")

    return edit_results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("edit_assembler round-trip test")
    print(f"Results directory: {RESULTS_DIR}")

    all_results = {}

    # --- HWPX samples ---
    hwpx_dir = SAMPLES_DIR / "표준계약서모음(hwp-hwpx)"
    hwpx_files = sorted(hwpx_dir.glob("*.hwpx")) if hwpx_dir.exists() else []
    for f in hwpx_files:
        try:
            results = test_hwpx(f)
            all_results[f.name] = results
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()

    # --- DOCX samples ---
    docx_files = sorted(SAMPLES_DIR.glob("*.docx"))
    for f in docx_files:
        try:
            results = test_docx(f)
            all_results[f.name] = results
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback; traceback.print_exc()

    # --- Summary ---
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    total_edits = 0
    total_warnings = 0
    for doc_name, results in all_results.items():
        n_edits = sum(r.opcodes_applied for _, r in results)
        n_warns = sum(len(r.warnings) for _, r in results)
        total_edits += n_edits
        total_warnings += n_warns
        print(f"  {doc_name}: {n_edits} edits applied, {n_warns} warnings")

    print(f"\n  Total: {total_edits} edits, {total_warnings} warnings")
    print(f"  Output files in: {RESULTS_DIR}")


if __name__ == "__main__":
    main()
