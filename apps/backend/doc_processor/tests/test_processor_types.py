from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = THIS_DIR.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from processor_types import (
    CellStyleInfo,
    DocIR,
    DocumentProcessState,
    ParaStyleInfo,
    ParagraphProcessState,
    ParagraphReviewResult,
    ParserSignals,
    RunStyleInfo,
    SourceType,
    SplitOp,
    StyleMap,
    TableStyleInfo,
    build_doc_ir_from_mapping,
)


class ProcessorTypesTests(unittest.TestCase):
    def _sample_mapping(self) -> dict[str, str]:
        return {
            "s1.p1.r1": "Hello ",
            "s1.p1.r2": "World",
            "s1.p2.r1.tbl1.tr1.tc1.p1.r1": "A1",
            "s1.p2.r1.tbl1.tr1.tc2.p1.r1": "B1",
            "s1.p2.r1.tbl1.tr2.tc1.p1.r1": "A2",
            "s1.p2.r1.tbl1.tr2.tc2.p1.r1": "B2",
            "s1.p3.r1": "Tail",
        }

    def _sample_style_map(self) -> StyleMap:
        return StyleMap(
            runs={
                "s1.p1.r1": RunStyleInfo(bold=True, size_pt=11.0),
                "s1.p1.r2": RunStyleInfo(italic=True, size_pt=11.0),
                "s1.p2.r1.tbl1.tr1.tc1.p1.r1": RunStyleInfo(underline=True),
            },
            paragraphs={
                "s1.p1": ParaStyleInfo(align="center"),
                "s1.p2": ParaStyleInfo(align="left"),
                "s1.p2.r1.tbl1.tr1.tc1.p1": ParaStyleInfo(align="right"),
            },
            cells={
                "s1.p2.r1.tbl1.tr1.tc1": CellStyleInfo(background="#ffeeaa"),
            },
            tables={
                "s1.p2.r1.tbl1": TableStyleInfo(row_count=2, col_count=2),
            },
        )

    def test_hierarchy_construction(self) -> None:
        doc_ir = build_doc_ir_from_mapping(self._sample_mapping())

        self.assertEqual(len(doc_ir.paragraphs), 3)
        self.assertEqual(doc_ir.paragraphs[0].unit_id, "s1.p1")
        self.assertEqual(doc_ir.paragraphs[0].text, "Hello World")
        self.assertEqual(doc_ir.paragraphs[1].unit_id, "s1.p2")
        self.assertEqual(doc_ir.paragraphs[1].source_type, SourceType.TABLE_BLOCK)
        self.assertEqual(len(doc_ir.paragraphs[1].tables), 1)

        table = doc_ir.paragraphs[1].tables[0]
        self.assertEqual(table.unit_id, "s1.p2.r1.tbl1")
        self.assertEqual(table.row_count, 2)
        self.assertEqual(table.col_count, 2)
        self.assertEqual(len(table.cells), 4)

    def test_legacy_id_compatibility(self) -> None:
        doc_ir = build_doc_ir_from_mapping(self._sample_mapping())

        run_pat = re.compile(r"^s\d+\.p\d+\.r\d+$")
        table_root_pat = re.compile(r"^s\d+\.p\d+\.r\d+\.tbl\d+$")
        table_cell_pat = re.compile(r"^s\d+\.p\d+\.r\d+\.tbl\d+\.tr\d+\.tc\d+$")
        table_run_pat = re.compile(
            r"^s\d+\.p\d+\.r\d+\.tbl\d+\.tr\d+\.tc\d+\.p\d+\.r\d+$"
        )

        for paragraph in doc_ir.paragraphs:
            self.assertTrue(paragraph.unit_id.startswith("s1.p"))
            for run in paragraph.runs:
                self.assertRegex(run.unit_id, run_pat)
            for table in paragraph.tables:
                self.assertRegex(table.unit_id, table_root_pat)
                for cell in table.cells:
                    self.assertRegex(cell.unit_id, table_cell_pat)
                    for cell_paragraph in cell.paragraphs:
                        for run in cell_paragraph.runs:
                            self.assertRegex(run.unit_id, table_run_pat)

    def test_style_embedding(self) -> None:
        style_map = self._sample_style_map()
        doc_ir = build_doc_ir_from_mapping(self._sample_mapping(), style_map=style_map)

        p1 = doc_ir.paragraphs[0]
        self.assertIsNotNone(p1.para_style)
        self.assertEqual(p1.para_style.align, "center")
        self.assertTrue(p1.runs[0].run_style is not None and p1.runs[0].run_style.bold)

        p2 = doc_ir.paragraphs[1]
        table = p2.tables[0]
        self.assertIsNotNone(table.table_style)
        cell = next(c for c in table.cells if c.unit_id.endswith("tr1.tc1"))
        self.assertIsNotNone(cell.cell_style)
        self.assertEqual(cell.cell_style.background, "#ffeeaa")
        cp = cell.paragraphs[0]
        self.assertIsNotNone(cp.para_style)
        self.assertEqual(cp.para_style.align, "right")
        self.assertTrue(cp.runs[0].run_style is not None and cp.runs[0].run_style.underline)

    def test_signals_validation(self) -> None:
        signals = ParserSignals(
            regex_clause={"value": "1", "span": (0, 3), "pattern": "x", "matched_text": "제1조"},
            bold=0.5,
            custom_feature=0.73,
        )
        self.assertIsNotNone(signals.regex_clause)
        self.assertAlmostEqual(signals.bold or 0.0, 0.5)
        self.assertEqual(signals.model_extra.get("custom_feature"), 0.73)

        paragraph = build_doc_ir_from_mapping({"s1.p1.r1": "X"}).paragraphs[0]
        self.assertIsNone(paragraph.parser_confidence)

        paragraph.parser_confidence = 0.61
        paragraph.candidate_labels = ["clause", "body"]
        paragraph.final_label = "body"
        paragraph.propagate_semantics_to_runs()

        run = paragraph.runs[0]
        self.assertEqual(run.candidate_labels, ["clause", "body"])
        self.assertEqual(run.parser_confidence, 0.61)
        self.assertEqual(run.final_label, "body")

    def test_from_mapping_stays_pure_no_regex_preprocess(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제1조 (목적)",
                "s1.p2.r1": "(1) 항목",
            }
        )
        self.assertIsNone(doc_ir.paragraphs[0].parser_signals.regex_clause)
        self.assertIsNone(doc_ir.paragraphs[1].parser_signals.regex_subclause)

    def test_annotate_numbering_signals_primary_and_subclause(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제1조 (목적)",
                "s1.p2.r1": "(1) 첫째",
                "s1.p3.r1": "(2) 둘째",
                "s1.p4.r1": "가. 하위 항목",
                "s1.p5.r1": "제2조 (범위)",
            }
        ).annotate_numbering_signals()

        self.assertEqual(doc_ir.paragraphs[0].parser_signals.regex_clause.value, "1")
        self.assertEqual(doc_ir.paragraphs[1].parser_signals.regex_subclause.value, "1")
        self.assertEqual(doc_ir.paragraphs[1].parser_signals.provisional_subclause_no, "1.1")
        self.assertEqual(doc_ir.paragraphs[2].parser_signals.provisional_subclause_no, "1.2")
        self.assertIsNone(doc_ir.paragraphs[3].parser_signals.regex_subclause)
        self.assertEqual(doc_ir.paragraphs[3].parser_signals.provisional_clause_no, "1")
        self.assertEqual(doc_ir.paragraphs[4].parser_signals.regex_clause.value, "2")

    def test_annotate_numbering_signals_fallback_when_no_primary(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "1. 시작",
                "s1.p2.r1": "본문",
                "s1.p3.r1": "2. 다음",
            }
        ).annotate_numbering_signals()

        self.assertEqual(doc_ir.paragraphs[0].parser_signals.regex_clause.value, "1")
        self.assertEqual(doc_ir.paragraphs[1].parser_signals.provisional_clause_no, "1")
        self.assertEqual(doc_ir.paragraphs[2].parser_signals.regex_clause.value, "2")

    def test_table_inherits_clause_context_from_parent_paragraph(self) -> None:
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "제1조 (목적)",
                "s1.p2.r1.tbl1.tr1.tc1.p1.r1": "표 내용",
            }
        ).annotate_numbering_signals()

        p_table = doc_ir.paragraphs[1]
        self.assertEqual(p_table.source_type, SourceType.TABLE_BLOCK)
        self.assertEqual(p_table.parser_signals.provisional_clause_no, "1")

    def test_split_ops_create_segments_without_modifying_runs(self) -> None:
        mapping = {
            "s1.p1.r1": "AAABBB",
            "s1.p1.r2": "CCCDDD",
        }
        doc_ir = DocIR.from_mapping(mapping)
        paragraph = doc_ir.paragraphs[0]
        original_run_ids = [run.unit_id for run in paragraph.runs]
        original_run_texts = [run.text for run in paragraph.runs]

        doc_ir.apply_review_results(
            [
                ParagraphReviewResult(
                    unit_id="s1.p1",
                    status="split",
                    reason="mixed units",
                    ops=[
                        SplitOp(op="split_unit", anchor_text="BBB", occurrence=1),
                        SplitOp(op="split_unit", anchor_text="DDD", occurrence=1),
                    ],
                )
            ]
        )

        self.assertEqual([run.unit_id for run in paragraph.runs], original_run_ids)
        self.assertEqual([run.text for run in paragraph.runs], original_run_texts)
        self.assertEqual(len(paragraph.segments), 3)
        self.assertEqual(paragraph.segments[1].text, "BBBCCC")
        self.assertEqual(len(paragraph.segments[1].run_spans), 2)

    def test_style_signal_aggregation_mean_and_bold_ratio(self) -> None:
        style_map = StyleMap(
            runs={
                "s1.p1.r1": RunStyleInfo(size_pt=10.0, bold=True),
                "s1.p1.r2": RunStyleInfo(size_pt=14.0, bold=False),
            }
        )
        doc_ir = DocIR.from_mapping(
            {
                "s1.p1.r1": "AB ",
                "s1.p1.r2": "CD",
            },
            style_map=style_map,
        ).recompute_style_signals()

        p1 = doc_ir.paragraphs[0]
        self.assertAlmostEqual(p1.parser_signals.font_size or 0.0, 12.0)
        self.assertAlmostEqual(p1.parser_signals.bold or 0.0, 0.5)

    def test_state_models_readiness(self) -> None:
        doc_ir = DocIR.from_mapping(
            self._sample_mapping(),
            source_path=Path("/tmp/sample.hwpx"),
        )

        state = DocumentProcessState(target_file=Path("/tmp/sample.hwpx"), doc_ir=doc_ir)
        self.assertEqual(len(state.formatted_content), len(doc_ir.paragraphs))

        worker_state = ParagraphProcessState(paragraph_idx=0, paragraph_ir=doc_ir.paragraphs[0])
        dumped = worker_state.model_dump()
        self.assertEqual(dumped["paragraph_idx"], 0)
        self.assertIn("paragraph_ir", dumped)


if __name__ == "__main__":
    unittest.main()
