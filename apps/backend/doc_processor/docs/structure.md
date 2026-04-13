## Package Structure

Current package layout:

```text
src/doc_processor/
├── main.py                 # run_phase1(...) convenience entrypoint
├── state.py                # WorkflowState and Phase1Config
├── types.py                # analysis/result/meta models
├── llm/
│   └── factory.py          # model/provider selection
├── observability/
│   └── langfuse.py         # Langfuse callback wiring and sanitization
├── prompts/
│   ├── loader.py
│   └── default/phase1/     # prompt templates used by the current stage
└── phase1/
    ├── graph.py            # compiled LangGraph definition
    ├── nodes.py            # workflow nodes and routing
    ├── parser.py           # regex / deterministic structure parsing
    ├── boundaries.py       # boundary suspect detection and boundary LLM review
    ├── labels.py           # deterministic labeling and label LLM review
    ├── relevance.py        # relevance screening
    ├── converters.py       # write analysis metadata back onto DocIR
    ├── selectors.py        # paragraph-level extraction helpers
    └── rules.py            # numbering rule definitions
```

Notes:

- The package directory is still named `phase1`, but logs and tracing refer to the stage as `structure_analysis`.
- `run_phase1(...)` is the public entrypoint today. Later stages should be added as separate packages rather than folded into the same router.
- Tests live in `tests/`, including `test_phase1.py`, `test_observability.py`, and the manual diagnostics notebook/scripts.
