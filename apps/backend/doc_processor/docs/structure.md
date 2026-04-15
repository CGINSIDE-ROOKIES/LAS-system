## Package Structure

Current package layout for the parser foundation and the next review/apply stages:

```text
src/doc_processor/
├── main.py                 # run_parser(...) convenience entrypoint
├── state.py                # WorkflowState and ParserConfig
├── types.py                # parser/review/apply models
├── llm/
│   └── factory.py          # model/provider selection
├── observability/
│   └── langfuse.py         # Langfuse callback wiring and sanitization
├── prompts/
│   ├── loader.py
│   └── default/parser/     # prompt templates used by the parser stage
├── parser/
│   ├── graph.py            # compiled LangGraph definition
│   ├── nodes.py            # workflow nodes and routing
│   ├── parser.py           # regex / deterministic structure parsing
│   ├── boundaries.py       # boundary suspect detection and boundary LLM review
│   ├── labels.py           # deterministic labeling and label LLM review
│   ├── relevance.py        # relevance screening
│   ├── converters.py       # write parser metadata back onto DocIR
│   ├── selectors.py        # paragraph-level extraction helpers
│   └── rules.py            # numbering rule definitions
├── review/                 # planned clause-level risk review graph
├── hitl/                   # planned pause/resume + suggestion resolution loop
└── apply/                  # planned native document write-back
```

Notes:

- External naming should use `document_parser` or `parser` for the current structure-analysis foundation.
- The package/code surface is already aligned on parser naming across paths, public APIs, and metadata fields.
- Follow-on stages should stay as separate packages instead of being folded into the parser router.
- Prompt/profile names, Langfuse tags, and API-visible field names should move to parser terminology together.
- Tests and manual diagnostics should mirror the same naming so the package surface stays consistent.
