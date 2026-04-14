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
        annotations = [
            Annotation(
                target_unit_id="s1.p1",
                start=6,
                end=11,
                label="Clause focus",
                color="#FFEE88",
                note="Important phrase",
            ),
            Annotation(
                target_unit_id="s1.p2.r1.tbl1.tr1.tc1.p1.r1",
                start=0,
                end=4,
                label="Cell review",
                color="#99EEFF",
            ),
        ]

        html = render_annotated_html(doc, annotations, title="Review")

        self.assertIn("<title>Review</title>", html)
        self.assertIn('data-unit-id="s1.p1"', html)
        self.assertIn('data-unit-id="s1.p1.r2"', html)
        self.assertIn('data-unit-id="s1.p2.r1.tbl1.tr1.tc1.p1.r1"', html)
        self.assertIn('data-label="Clause focus"', html)
        self.assertIn('data-note="Important phrase"', html)
        self.assertGreaterEqual(html.count("<mark "), 2)
        self.assertIn("World", html)
        self.assertIn("Cell", html)

    def test_resolve_annotations_rejects_out_of_bounds_ranges(self) -> None:
        doc = DocIR.from_mapping({"s1.p1.r1": "Hello"})

        with self.assertRaises(AnnotationValidationError):
            resolve_annotations(
                doc,
                [
                    Annotation(
                        target_unit_id="s1.p1.r1",
                        start=0,
                        end=10,
                        label="Too long",
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
