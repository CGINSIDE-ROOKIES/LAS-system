from __future__ import annotations

import unittest

from document_processor import DocIR

from doc_processor.api import DocumentInput, TextAnnotation, render_review_html


class AnnotationTests(unittest.TestCase):
    def test_render_review_html_highlights_paragraph_and_run_targets(self) -> None:
        doc = DocIR.from_mapping(
            {
                "s1.p1.r1": "Hello ",
                "s1.p1.r2": "World",
                "s1.p2.r1.tbl1.tr1.tc1.p1.r1": "Cell text",
            }
        )
        paragraph_id = doc.paragraphs[0].node_id
        run_id = doc.paragraphs[0].runs[1].node_id
        first_cell = next(doc.paragraphs[1].tables[0].iter_cells())
        cell_run_id = first_cell.paragraphs[0].runs[0].node_id

        result = render_review_html(
            document=DocumentInput(doc_ir=doc),
            annotations=[
                TextAnnotation(
                    target_kind="paragraph",
                    target_id=paragraph_id,
                    selected_text="World",
                    label="Clause focus",
                    color="#FFEE88",
                    note="Important phrase",
                ),
                TextAnnotation(
                    target_kind="run",
                    target_id=cell_run_id,
                    selected_text="Cell",
                    label="Cell review",
                    color="#99EEFF",
                ),
            ],
            title="Review",
        )

        self.assertTrue(result.ok)
        html = result.html or ""
        self.assertIn("<title>Review</title>", html)
        self.assertIn(f'data-node-id="{paragraph_id}"', html)
        self.assertIn(f'data-node-id="{run_id}"', html)
        self.assertIn(f'data-node-id="{cell_run_id}"', html)
        self.assertIn('data-label="Clause focus"', html)
        self.assertIn('data-note="Important phrase"', html)
        self.assertGreaterEqual(html.count("<mark "), 2)
        self.assertIn("World", html)
        self.assertIn("Cell", html)

    def test_render_review_html_rejects_missing_selected_text(self) -> None:
        doc = DocIR.from_mapping({"s1.p1.r1": "Hello"})
        run_id = doc.paragraphs[0].runs[0].node_id

        result = render_review_html(
            document=DocumentInput(doc_ir=doc),
            annotations=[
                TextAnnotation(
                    target_kind="run",
                    target_id=run_id,
                    selected_text="World",
                    label="Missing",
                )
            ],
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.validation.issues[0].code, "selected_text_not_found")

    def test_render_review_html_requires_occurrence_for_ambiguous_text(self) -> None:
        doc = DocIR.from_mapping({"s1.p1.r1": "Hello Hello"})
        run_id = doc.paragraphs[0].runs[0].node_id

        result = render_review_html(
            document=DocumentInput(doc_ir=doc),
            annotations=[
                TextAnnotation(
                    target_kind="run",
                    target_id=run_id,
                    selected_text="Hello",
                    label="Ambiguous",
                )
            ],
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.validation.issues[0].code, "selected_text_ambiguous")


if __name__ == "__main__":
    unittest.main()
