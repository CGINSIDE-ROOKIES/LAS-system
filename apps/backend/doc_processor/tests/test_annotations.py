from __future__ import annotations

import unittest

from document_processor import DocIR

from doc_processor.annotations import Annotation, AnnotationValidationError, render_annotated_html, resolve_annotations


class AnnotationTests(unittest.TestCase):
    def test_render_annotated_html_highlights_paragraph_and_table_cell_targets(self) -> None:
        doc = DocIR.from_mapping(
            {
                "s1.p1.r1": "Hello ",
                "s1.p1.r2": "World",
                "s1.p2.r1.tbl1.tr1.tc1.p1.r1": "Cell text",
            }
        )
        paragraph_id = doc.paragraphs[0].node_id
        run_id = doc.paragraphs[0].runs[1].node_id
        cell_run_id = doc.paragraphs[1].tables[0].cells[0].paragraphs[0].runs[0].node_id
        annotations = [
            Annotation(
                target_id=paragraph_id,
                selected_text="World",
                label="Clause focus",
                color="#FFEE88",
                note="Important phrase",
            ),
            Annotation(
                target_id=cell_run_id,
                selected_text="Cell",
                label="Cell review",
                color="#99EEFF",
            ),
        ]

        html = render_annotated_html(doc, annotations, title="Review")

        self.assertIn("<title>Review</title>", html)
        self.assertIn(f'data-node-id="{paragraph_id}"', html)
        self.assertIn(f'data-node-id="{run_id}"', html)
        self.assertIn(f'data-node-id="{cell_run_id}"', html)
        self.assertIn('data-label="Clause focus"', html)
        self.assertIn('data-note="Important phrase"', html)
        self.assertGreaterEqual(html.count("<mark "), 2)
        self.assertIn("World", html)
        self.assertIn("Cell", html)

    def test_resolve_annotations_rejects_missing_selected_text(self) -> None:
        doc = DocIR.from_mapping({"s1.p1.r1": "Hello"})
        run_id = doc.paragraphs[0].runs[0].node_id

        with self.assertRaises(AnnotationValidationError):
            resolve_annotations(
                doc,
                [
                    Annotation(
                        target_id=run_id,
                        selected_text="World",
                        label="Missing",
                    )
                ],
            )

    def test_resolve_annotations_requires_occurrence_for_ambiguous_text(self) -> None:
        doc = DocIR.from_mapping({"s1.p1.r1": "Hello Hello"})
        run_id = doc.paragraphs[0].runs[0].node_id

        with self.assertRaises(AnnotationValidationError):
            resolve_annotations(
                doc,
                [
                    Annotation(
                        target_id=run_id,
                        selected_text="Hello",
                        label="Ambiguous",
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
