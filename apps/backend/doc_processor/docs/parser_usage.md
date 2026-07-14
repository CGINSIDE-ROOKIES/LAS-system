# Parser Stage Notes

This document uses the target external names for the current structure-analysis
foundation:

- package: `doc_processor.parser`
- public entrypoints: `run_parser(...)`, `build_parser_graph()`
- config/result surface: `ParserConfig`, `parser_analysis`, `parser_result`
- document metadata: `paragraph.meta.parser`, `working_doc.meta.parser_doc`

For LLM and tool-call integration, use
[llm_tool_api.md](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/docs/llm_tool_api.md).
That guide documents the compact request/response surface built on top of the
parser internals and the separate edit engine.

Current parser package/code surface:

- package directory: `src/doc_processor/parser`
- public entrypoints: `run_parser(...)`, `build_parser_graph()`
- core types: `ParserConfig`, `ParserResult`, `ParserAnalysis`, `Parser*Meta`
- state fields: `parser_config`, `parser_analysis`, `parser_result`
- metadata fields: `paragraph.meta.parser`, `working_doc.meta.parser_doc`

## Current Scope

Current parser behavior:

- document loading through `document-processor`
- optional relevance screening
- deterministic clause/subclause parsing
- boundary suspect detection
- optional LLM review for relevance / boundaries / ambiguous labels
- clause/subclause entry generation
- writing parser metadata back onto `working_doc`

Current graph nodes:

- `load_document`
- `screen_relevance`
- `regex_analysis`
- `llm_analysis`
- `boundary_llm_batch`
- `llm_analysis_worker`
- `finalize_llm`

## LLM Usage

The parser stage can call LLMs for:

- relevance fallback
- boundary review
- ambiguous paragraph labeling

The existing flow is intentionally sparse:

- deterministic parsing stays primary
- LLM review is used only where the parser is uncertain
- clause-level risk review is a later stage, not part of the parser itself

## Observability

Recommended observability naming:

- trace name: `doc_processor.document_parser`
- tags: `document_parser`, `structure_analysis`
- graph/node progress events should use parser wording consistently

Parser traces should keep the same current behavior:

- retain graph visibility
- sanitize `DocIR` inputs/outputs before sending them to Langfuse
- trace LLM generations normally

## Result Shape

The parser stage should expose the following stable concepts:

- `working_doc`
- `parser_analysis`
- `parser_result`
- `working_doc.meta.parser_doc`
- `working_doc.meta.parser_doc.clause_entries`

Per-paragraph parser metadata should live at:

- `paragraph.meta.parser`

Document-level parser metadata should live at:

- `working_doc.meta.parser_doc`

## Current Limits

- table internals are not segmented; tables inherit the owning paragraph context
- split review only covers boundary corrections, not full paragraph restructuring
- clause-level risk review is not part of the parser stage yet
- pause/resume human review is not part of the graph yet
- native source-document write-back exists through `doc_processor.api.apply_document_edits`, but only for `docx`/`hwp`/`hwpx`
- PDF should be treated as a suggestion-only format until a dedicated ingest path exists

## Prior Reference Implementation

Previous annotation/editing work exists in:

- `apps/backend/doc-processor-old/doc_processor/review_pipeline.py`
- `apps/backend/doc-processor-old/doc_processor/risk_analyzer.py`
- `apps/backend/doc-processor-old/doc_processor/core/html_exporter.py`
- `apps/backend/doc-processor-old/doc_processor/core/edit_assembler.py`

The IR is different now, but the high-level product shape is still relevant:

- clause/article review produces highlights and reports
- the user-facing review surface is HTML
- accepted edits are eventually applied back to the native document
