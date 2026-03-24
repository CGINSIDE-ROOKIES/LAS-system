"""
annotation_test — test ArticleAnnotations + highlight export
============================================================

Creates mock ArticleAnnotations for a few IR groups and exports
annotated HTML to tests/results/ for visual inspection.

Run:
    python -m tests.annotation_test
"""

import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from doc_processor.core.ir import create_ir_dict, create_ir_dict_from_mapping, ir_grouper
from doc_processor.core.docx_ir import export_docx_structured
from doc_processor.core.style_extractor import extract_styles_hwpx, extract_styles_docx
from doc_processor.core.html_exporter import export_html
from doc_processor.las_types import ArticleAnnotations, Highlight

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
SAMPLES_DIR = Path(__file__).resolve().parent / "doc_samples"


def make_mock_annotations(ir_groups) -> dict[int, ArticleAnnotations]:
    """Create simple mock annotations: highlight the first 20 chars of a few groups."""
    annotations: dict[int, ArticleAnnotations] = {}

    colors = ["#FFFF00", "#90EE90", "#ADD8E6", "#FFB6C1", "#FFA500"]

    for idx, grp in enumerate(ir_groups):
        text = grp.formatted_str.strip()
        if not text or len(text) < 10:
            continue

        highlights = []

        # Highlight the first non-whitespace token (up to 20 chars)
        first_chunk = text[:min(20, len(text))]
        highlights.append(Highlight(
            text=first_chunk,
            label=f"그룹 {idx} 첫 부분",
            color=colors[idx % len(colors)],
            occurrence=1,
        ))

        # If the article is long enough, highlight a middle chunk too
        if len(text) > 60:
            mid = len(text) // 2
            mid_chunk = text[mid:mid + 15].strip()
            if mid_chunk:
                highlights.append(Highlight(
                    text=mid_chunk,
                    label="중간 강조",
                    color="#FF69B4",
                    occurrence=1,
                ))

        annotations[idx] = ArticleAnnotations(
            reasoning=f"그룹 {idx} 테스트 하이라이트 (article_n={grp.article_n})",
            highlights=highlights,
        )

        if idx >= 9:  # Only annotate first 10 groups to keep output manageable
            break

    return annotations


def test_hwpx_annotations(hwpx_path: Path):
    from hwpx import HwpxDocument

    stem = hwpx_path.stem
    print(f"\n{'='*60}")
    print(f"HWPX ANNOTATION TEST: {stem}")
    print(f"{'='*60}")

    with HwpxDocument.open(hwpx_path) as doc:
        ir_dict = create_ir_dict(doc)
        ir_groups = ir_grouper(ir_dict)
        style_map = extract_styles_hwpx(doc)

    print(f"  IR groups: {len(ir_groups)}")
    annotations = make_mock_annotations(ir_groups)
    print(f"  Annotations created for groups: {sorted(annotations.keys())}")

    # Sanity-check resolve() for each annotated group
    for idx, ann in annotations.items():
        grp = ir_groups[idx]
        resolved = ann.resolve(grp.formatted_str)
        print(f"    group[{idx}] article={grp.article_n}: "
              f"{len(ann.highlights)} highlights → {len(resolved)} resolved")
        for h, r in zip(ann.highlights, resolved):
            matched = grp.formatted_str[r.start:r.end]
            ok = matched == h.text
            print(f"      '{h.text[:30]}' → [{r.start}:{r.end}] {'OK' if ok else 'MISMATCH: got ' + repr(matched)}")

    html = export_html(ir_groups, style_map, title=f"{stem} (annotated)", annotations=annotations)
    out = RESULTS_DIR / f"{stem}_annotated.html"
    out.write_text(html, encoding="utf-8")
    print(f"  -> {out.name}")


def test_docx_annotations(docx_path: Path):
    stem = docx_path.stem
    print(f"\n{'='*60}")
    print(f"DOCX ANNOTATION TEST: {stem}")
    print(f"{'='*60}")

    parsed = export_docx_structured(docx_path)
    ir_dict = create_ir_dict_from_mapping(parsed)
    ir_groups = ir_grouper(ir_dict)
    style_map = extract_styles_docx(docx_path)

    print(f"  IR groups: {len(ir_groups)}")
    annotations = make_mock_annotations(ir_groups)
    print(f"  Annotations created for groups: {sorted(annotations.keys())}")

    for idx, ann in annotations.items():
        grp = ir_groups[idx]
        resolved = ann.resolve(grp.formatted_str)
        print(f"    group[{idx}] article={grp.article_n}: "
              f"{len(ann.highlights)} highlights → {len(resolved)} resolved")

    html = export_html(ir_groups, style_map, title=f"{stem} (annotated)", annotations=annotations)
    out = RESULTS_DIR / f"{stem}_annotated.html"
    out.write_text(html, encoding="utf-8")
    print(f"  -> {out.name}")


def main():
    print("ArticleAnnotations export test")
    print(f"Results: {RESULTS_DIR}")

    hwpx_dir = SAMPLES_DIR / "표준계약서모음(hwp-hwpx)"
    hwpx_files = sorted(hwpx_dir.glob("*.hwpx")) if hwpx_dir.exists() else []
    for f in hwpx_files:
        try:
            test_hwpx_annotations(f)
        except Exception as e:
            print(f"  ERROR ({f.name}): {e}")
            import traceback; traceback.print_exc()

    docx_files = sorted(SAMPLES_DIR.glob("*.docx"))
    for f in docx_files:
        try:
            test_docx_annotations(f)
        except Exception as e:
            print(f"  ERROR ({f.name}): {e}")
            import traceback; traceback.print_exc()

    print("\nDone.")


if __name__ == "__main__":
    main()
