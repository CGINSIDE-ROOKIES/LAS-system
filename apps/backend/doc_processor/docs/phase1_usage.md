# Phase 1 Usage

This document shows how to manually run and inspect the phase-1 clause parser in:

- [src/doc_processor](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor)

Phase 1 currently does:

- document loading through `document-processor`
- optional relevance screening
- deterministic clause/subclause parsing
- boundary suspect detection
- optional LLM review for relevance / boundaries / ambiguous labels
- fixed paragraph-category labeling
- clause/subclause entry generation
- writing phase-1 metadata back onto `working_doc`

## Environment

Run commands from:

```bash
cd /home/maxjo/Work/LAS-system/apps/backend/doc_processor
```

Use the local venv and `src/` import path:

```bash
PYTHONPATH=src .venv/bin/python ...
```

## Main entrypoints

The main convenience API is:

- [run_phase1](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/main.py)

You can also compile/invoke the graph directly via:

- [build_phase1_graph](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/phase1/graph.py)

Relevant types:

- [Phase1Config](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/state.py)
- [WorkflowState](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/state.py)
- [WorkflowMeta](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/types.py)
- [ClauseEntry](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/types.py)

## Quick deterministic run

This is the safest manual test path when you do not want any model calls:

```bash
cd /home/maxjo/Work/LAS-system/apps/backend/doc_processor

PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path

from doc_processor import Phase1Config, run_phase1
from doc_processor.types import RelevanceMode

state = run_phase1(
    Path("tests/doc_samples/new_test/02. 청소년 대중문화예술인 표준 부속합의서.hwpx"),
    config=Phase1Config(
        relevance_mode=RelevanceMode.KEYWORD_ONLY,
        boundary_review_enabled=False,
        label_review_enabled=False,
    ),
)

print("accepted:", state.phase1_result.accepted)
print("clause rule:", state.phase1_result.clause_rule_name)
print("subclause rule:", state.phase1_result.subclause_rule_name)
print("clause count:", state.phase1_result.clause_count)
print("subclause count:", state.phase1_result.subclause_count)
print("boundary suspects:", state.phase1_result.boundary_suspect_unit_ids[:10])
PY
```

## Relevance modes

Configured through:

- `Phase1Config.relevance_mode`

Available values:

- `RelevanceMode.DISABLED`
  - skip relevance screening entirely
- `RelevanceMode.KEYWORD_ONLY`
  - deterministic keyword/rule scoring only
- `RelevanceMode.KEYWORD_THEN_LLM`
  - deterministic scoring first
  - only ambiguous cases fall back to an LLM

Example:

```python
from doc_processor import Phase1Config
from doc_processor.types import RelevanceMode

config = Phase1Config(
    relevance_mode=RelevanceMode.KEYWORD_THEN_LLM,
)
```

## LLM-backed manual testing

Phase 1 can call LLMs for:

- relevance fallback
- boundary review
- ambiguous paragraph labels

Those paths use the package-local factory:

- [llm/factory.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/llm/factory.py)

Prompt files live here:

- [prompts/default/phase1](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/prompts/default/phase1)

## Langfuse observability

Phase 1 now has optional Langfuse instrumentation for:

- the top-level `run_phase1(...)` execution
- each graph node as a nested span
- LangChain/LangGraph-compatible LLM calls through Langfuse's `CallbackHandler`

The integration code lives here:

- [observability/langfuse.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/observability/langfuse.py)

### Config fields

Observability is controlled through [Phase1Config](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/state.py):

- `langfuse_enabled`
  - `None`: auto-enable only if SDK + credentials are present
  - `True`: require Langfuse and raise if missing
  - `False`: disable tracing
- `langfuse_trace_name`
- `langfuse_user_id`
- `langfuse_session_id`
- `langfuse_tags`
- `langfuse_metadata`
- `langfuse_environment`
- `langfuse_release`
- `langfuse_flush_at_end`

### Required env vars

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
# or https://us.cloud.langfuse.com
```

### Example

```bash
cd /home/maxjo/Work/LAS-system/apps/backend/doc_processor

PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path

from doc_processor import Phase1Config, run_phase1
from doc_processor.types import RelevanceMode

state = run_phase1(
    Path("tests/doc_samples/new_test/02. 청소년 대중문화예술인 표준 부속합의서.hwpx"),
    config=Phase1Config(
        relevance_mode=RelevanceMode.KEYWORD_THEN_LLM,
        boundary_review_enabled=True,
        label_review_enabled=True,
        langfuse_enabled=True,
        langfuse_trace_name="doc_processor.phase1.manual",
        langfuse_session_id="manual-test-01",
        langfuse_tags=["phase1", "manual"],
        langfuse_metadata={"source": "manual_test"},
    ),
)

print(state.phase1_result.model_dump(mode="json"))
PY
```

### Environment variables

Default variables:

```bash
DOC_PROCESSOR_LLM_PROVIDER=openai_compat
DOC_PROCESSOR_LLM_MODEL=...
DOC_PROCESSOR_LLM_BASE_URL=...
DOC_PROCESSOR_LLM_API_KEY=...
```

Profile-specific overrides also work:

```bash
DOC_PROCESSOR_LLM_RELEVANCE_PROVIDER=gemini
DOC_PROCESSOR_LLM_RELEVANCE_MODEL=gemini-2.5-flash

DOC_PROCESSOR_LLM_BOUNDARY_PROVIDER=gemini
DOC_PROCESSOR_LLM_BOUNDARY_MODEL=gemini-2.5-flash

DOC_PROCESSOR_LLM_LABEL_PROVIDER=gemini
DOC_PROCESSOR_LLM_LABEL_MODEL=gemini-2.5-flash
```

You can also set:

```bash
DOC_PROCESSOR_LLM_<PROFILE>_STRUCTURED_METHOD=json_mode
DOC_PROCESSOR_LLM_<PROFILE>_STRUCTURED_METHOD=json_schema
```

### Example with LLM review enabled

```bash
cd /home/maxjo/Work/LAS-system/apps/backend/doc_processor

PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path

from doc_processor import Phase1Config, run_phase1
from doc_processor.types import RelevanceMode

state = run_phase1(
    Path("tests/doc_samples/new_test/02. 청소년 대중문화예술인 표준 부속합의서.hwpx"),
    config=Phase1Config(
        relevance_mode=RelevanceMode.KEYWORD_THEN_LLM,
        boundary_review_enabled=True,
        label_review_enabled=True,
        relevance_llm_profile="relevance",
        boundary_llm_profile="boundary",
        label_llm_profile="label",
    ),
)

print(state.phase1_result.model_dump(mode="json"))
PY
```

## Inspecting results

The graph returns a [WorkflowState](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/state.py).

Important fields:

- `state.phase1_result`
- `state.phase1_analysis`
- `state.working_doc`
- `state.working_doc.meta.phase1_doc`

Per-paragraph phase-1 metadata is written to:

- `paragraph.meta.phase1`

Document-level phase-1 metadata is written to:

- `working_doc.meta.phase1_doc`

### Example: inspect labeled paragraphs

```bash
cd /home/maxjo/Work/LAS-system/apps/backend/doc_processor

PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path

from doc_processor import Phase1Config, run_phase1
from doc_processor.types import RelevanceMode

state = run_phase1(
    Path("tests/doc_samples/new_test/02. 청소년 대중문화예술인 표준 부속합의서.hwpx"),
    config=Phase1Config(
        relevance_mode=RelevanceMode.KEYWORD_ONLY,
        boundary_review_enabled=False,
        label_review_enabled=False,
    ),
)

for paragraph in state.working_doc.paragraphs:
    if not paragraph.text.strip():
        continue
    meta = paragraph.meta.phase1 if paragraph.meta else None
    if meta is None:
        continue
    print(
        paragraph.unit_id,
        meta.category,
        meta.clause_no,
        meta.subclause_no,
        paragraph.text[:120].replace("\\n", " "),
    )
PY
```

### Example: inspect clause entries

```bash
cd /home/maxjo/Work/LAS-system/apps/backend/doc_processor

PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path

from doc_processor import Phase1Config, run_phase1
from doc_processor.phase1.converters import clause_entry_to_targets, resolve_clause_entry
from doc_processor.types import RelevanceMode

state = run_phase1(
    Path("tests/doc_samples/new_test/02. 청소년 대중문화예술인 표준 부속합의서.hwpx"),
    config=Phase1Config(
        relevance_mode=RelevanceMode.KEYWORD_ONLY,
        boundary_review_enabled=False,
        label_review_enabled=False,
    ),
)

entries = state.working_doc.meta.phase1_doc.clause_entries
first = entries[0]

print("clause:", first.clause_no, first.title)
print("members:", first.member_unit_ids)
print("targets:", [target.unit_id for target in clause_entry_to_targets(first)])
print("resolved:", [p.unit_id for p in resolve_clause_entry(state.working_doc, first)])
PY
```

## Manual testing against preloaded `DocIR`

You do not need to read from file every time.

If you already have a `DocIR`, create `WorkflowState` manually and invoke the graph:

```bash
cd /home/maxjo/Work/LAS-system/apps/backend/doc_processor

PYTHONPATH=src .venv/bin/python - <<'PY'
from doc_processor import Phase1Config, WorkflowState
from doc_processor.phase1.graph import build_phase1_graph
from doc_processor.types import RelevanceMode
from document_processor import DocIR

doc = DocIR.from_mapping(
    {
        "s1.p1.r1": "표준근로계약서",
        "s1.p2.r1": "제1조 (목적) ① 갑은 을에게 업무를 위탁한다.",
        "s1.p3.r1": "② 을은 성실히 업무를 수행한다.",
        "s1.p4.r1": "제2조 (기간) 계약기간은 1년으로 한다.",
    }
)

graph = build_phase1_graph()
state = WorkflowState(
    base_doc=doc,
    working_doc=doc,
    phase1_config=Phase1Config(
        relevance_mode=RelevanceMode.DISABLED,
        boundary_review_enabled=False,
        label_review_enabled=False,
    ),
)

result = WorkflowState.model_validate(graph.invoke(state))
print(result.phase1_result.model_dump(mode="json"))
PY
```

## Suggested manual test matrix

Use these samples first:

Contract-like:

- `tests/doc_samples/new_test/02. 청소년 대중문화예술인 표준 부속합의서.hwpx`
- `tests/doc_samples/new_test/표준근로계약서.hwp`
- `tests/doc_samples/new_test/style_test_sample.docx`

Clearly non-contract:

- `tests/doc_samples/new_test/2026년_전통시장_육성사업(백년시장)_모집공고(수정).hwpx`
- `tests/doc_samples/new_test/251029 2025년 3회 추경 사업설명서(평화협력국)_최종.hwpx`

Recommended checks:

1. `KEYWORD_ONLY` on obvious contract docs
2. `KEYWORD_ONLY` on obvious non-contract docs
3. `DISABLED` on non-contract docs, to inspect raw structural parsing without rejection
4. `KEYWORD_THEN_LLM` with boundary/label review enabled on ambiguous docs

## Current result shape

At the end of phase 1:

- `working_doc` is a normal `DocIR`
- paragraph/table/doc `.meta` is populated with [WorkflowMeta](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/types.py)
- clause entries are stored in:
  - `working_doc.meta.phase1_doc.clause_entries`

Important design detail:

- the parse path currently loads through plain `DocIR`
- then phase-1 metadata is attached onto the finalized `working_doc`
- this avoids nested generic Pydantic rebuild issues during `document-processor` parsing

## Limitations in current phase 1

- table internals are not segmented; tables inherit the owning paragraph context
- LLM split review currently records split suggestions and limited span trimming, not full paragraph restructuring
- relevance/boundary/label LLM steps are optional and sparse by design
- no clause-level worker fan-out yet; this is still the phase-1 foundation

## Test command

The current automated test entrypoint is:

```bash
cd /home/maxjo/Work/LAS-system/apps/backend/doc_processor
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```
