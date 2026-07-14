## Parser Status

Terminology:

- `clause` = `조`
- `subclause` = `항`
- `호`, `목` remain out of scope for now

Current parser coverage:

1. Load a document into `DocIR`
2. Optionally reject obviously irrelevant documents
3. Parse clause/subclause structure with deterministic numbering rules
4. Detect boundary suspects
5. Review boundary suspects with a batch LLM call when enabled
6. Label paragraphs deterministically
7. Review only ambiguous labels with per-unit LLM workers when enabled
8. Write parser metadata back onto `working_doc`

Important implementation details:

- Clause and subclause numbering rules are chosen at the document level.
- Paragraph metadata should be exposed as `paragraph.meta.parser`.
- Document-level metadata should be exposed as `working_doc.meta.parser_doc`.
- Tables inherit the owning paragraph context for now.

Current graph shape:

- `load_document`
- `screen_relevance`
- `regex_analysis`
- `llm_analysis`
- `boundary_llm_batch`
- `llm_analysis_worker`
- `finalize_llm`

Planned next work:

1. Keep the parser stage separate from downstream review/apply stages
2. Add richer tail/signature detachment around contract endings
3. Add clause-level risk review and annotation stages
4. Add pause/resume human review on top of versioned `DocIR`
5. Add native document write-back plus re-parse verification
6. Add API orchestration in `apps/backend/api`

Detailed API planning lives in:

- [api_integration_plan.md](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/docs/api_integration_plan.md)
