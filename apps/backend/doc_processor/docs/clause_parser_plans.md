## Structure Analysis Status

Terminology:

- `clause` = `조`
- `subclause` = `항`
- `호`, `목` are still out of scope

Current stage coverage:

1. Load a document into `DocIR`
2. Optionally reject obviously irrelevant documents
3. Parse clause/subclause structure with deterministic numbering rules
4. Detect boundary suspects
5. Review boundary suspects with a batch LLM call when enabled
6. Label paragraphs deterministically
7. Review only ambiguous labels with per-unit LLM workers when enabled
8. Write structure metadata back onto `working_doc`

Important implementation details:

- Clause and subclause numbering rules are chosen at the document level, not by “first thing seen wins”.
- Paragraph metadata is attached through `paragraph.meta.phase1`.
- Document-level metadata is attached through `working_doc.meta.phase1_doc`.
- Tables inherit the owning paragraph context for now.

Current graph shape:

- `load_document`
- `screen_relevance`
- `regex_analysis`
- `llm_analysis`
- `boundary_llm_batch`
- `llm_analysis_worker`
- `finalize_llm`

Planned later work:

1. Separate follow-on analysis stages instead of expanding the current router
2. Richer tail/signature detachment around contract endings
3. Clause-level risk review and annotation stages
4. Human-in-the-loop edit application on top of versioned `DocIR`
