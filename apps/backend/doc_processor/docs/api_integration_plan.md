# API Integration Plan

This note covers the planned integration between `apps/backend/doc_processor`
and `apps/backend/api`, with dependency injection centered in
[dependencies.py](/home/maxjo/Work/LAS-system/apps/backend/api/src/dependencies.py).

## Parser Surface

The current parser-facing names are the canonical names for the API plan:

- package directory: `src/doc_processor/parser`
- public entrypoints: `run_parser(...)`, `build_parser_graph()`
- core types: `ParserConfig`, `ParserAnalysis`, `ParserResult`, `Parser*Meta`
- workflow state fields: `parser_config`, `parser_analysis`, `parser_result`
- metadata fields: `paragraph.meta.parser`, `working_doc.meta.parser_doc`
- prompts/tests/manual tooling: parser naming throughout

## Target User Flow

1. Upload document
2. Parse document with the existing LangGraph parser
3. Run clause-level risk review and annotation stages
4. Pause for human review and return structured suggestions
5. User accepts, rejects, or gives feedback on each suggestion
6. Repeat until all suggestions are resolved
7. Apply accepted edits to the native source document
8. Re-parse for verification and return a downloadable result

PDF rule:

- PDF stops after the suggestion/annotation step
- no native edit application
- no edited-document download

## Current Constraints

The integration plan has three real blockers that should be treated as
explicit milestones:

1. Runtime mismatch:
<<<<<<< HEAD
   - `apps/backend/api/pyproject.toml` is pinned to Python `3.13`
=======
   - `apps/backend/api/pyproject.toml` is pinned to Python `3.12`
>>>>>>> origin/refactor/api-integration
   - `apps/backend/doc_processor/pyproject.toml` currently requires Python `>=3.13`
2. PDF ingest gap:
   - `document_processor.DocIR.from_file(..., doc_type="pdf")` is not implemented
3. Native write-back gap:
   - `DocIR` is a read model, not the source of truth for round-trip editing
   - native write-back needs a resolver/anchor layer before edit application is safe

The native write-back constraint is already consistent with
[llm-editing-notes.md](/home/maxjo/Work/document-processor/docs/llm-editing-notes.md).

## Previous Implementation References

Earlier annotation/editing work already exists in:

- `apps/backend/doc-processor-old/doc_processor/review_pipeline.py`
- `apps/backend/doc-processor-old/doc_processor/risk_analyzer.py`
- `apps/backend/doc-processor-old/doc_processor/core/html_exporter.py`
- `apps/backend/doc-processor-old/doc_processor/core/edit_assembler.py`

The IR has changed, so these files should not be ported mechanically. The main
reusable ideas are:

- risk review produces structured highlights/annotations
- the review surface is rendered as HTML
- accepted edits are applied back to the native source document
- annotation generation and edit application should remain separate stages

## Recommended Integration Boundary

Recommended path:

- align `apps/backend/api` to the same Python runtime as `doc_processor`
- add `doc_processor` as an API dependency
- keep parser/review/apply orchestration behind service interfaces in `api`
- treat the LangGraph parser as an internal engine, not a router concern

Fallback path if runtime alignment is delayed:

- keep the same service interface in `api`
- back it with an internal worker/service call instead of direct imports
- preserve the same request/response and event schema so the API layer does not change later

## Dependency Injection Plan

Add the document-review providers to
[dependencies.py](/home/maxjo/Work/LAS-system/apps/backend/api/src/dependencies.py).

Suggested providers:

- `get_document_storage()`
  - persists original uploads, graph checkpoints, serialized `DocIR` snapshots, and final artifacts
- `get_document_parser_runner()`
  - wraps `run_parser(...)` or the compiled parser graph
- `get_document_review_service()`
  - orchestrates parse, clause review, annotation generation, and HITL pause/resume
- `get_document_checkpoint_store()`
  - persistent LangGraph checkpoint store keyed by review/job id
- `get_document_apply_service()`
  - applies accepted edit commands back to native source documents
- `get_document_download_service()`
  - resolves final artifact paths and download metadata

DI guidance:

- use `@lru_cache(maxsize=1)` only for stateless heavy services
- keep DB connections request-scoped through `get_db()`
- keep storage/checkpoint configuration centralized so routers stay thin

## API Surface Plan

Add a dedicated router such as `src/routers/document_reviews.py`.

Suggested endpoints:

- `POST /api/v1/document-reviews`
  - upload a document and create a review job
- `GET /api/v1/document-reviews/{review_id}`
  - fetch current status, progress, unresolved suggestions, and artifact availability
- `GET /api/v1/document-reviews/{review_id}/events`
  - SSE stream for progress updates and pause/resume events
- `POST /api/v1/document-reviews/{review_id}/suggestions/{suggestion_id}/decision`
  - accept, reject, or return feedback for a single suggestion
- `POST /api/v1/document-reviews/{review_id}/resume`
  - continue the graph after a batch of human decisions
- `GET /api/v1/document-reviews/{review_id}/download`
  - download the edited native file when available

## Workflow Shape

### 1. Upload + Parse

- save the original upload first
- create a review record with status `queued`
- run the existing parser graph
- persist the parser output as version `v1`
- derive the clause queue from `working_doc.meta.parser_doc.clause_entries`

### 2. Clause Review + Annotation

- review one clause or clause batch at a time
- generate structured risk findings, annotations, and edit suggestions
- anchor every suggestion to stable unit ids and clause ids from parser output
- persist each suggestion with status `pending`
- prepare HTML-oriented annotation payloads for the later live review UI

Suggested suggestion payload shape:

- `suggestion_id`
- `clause_id`
- `target_unit_ids`
- `risk_level`
- `annotation`
- `proposed_edit`
- `rationale`
- `status`

### 3. HITL Pause/Resume

Required behavior:

- the graph pauses after producing a reviewable suggestion batch
- the API returns unresolved suggestions to the client
- the user can accept, reject, or give feedback
- only the affected suggestion or clause is regenerated when feedback requests a revision
- the graph resumes and pauses again until nothing unresolved remains

Implementation direction:

- use a persistent LangGraph checkpointer keyed by `review_id`
- treat each pause as a durable checkpoint, not an in-memory wait state
- keep human decisions outside the graph state until they are validated and appended as input

## Progress Bar Plan

The UI progress bar should be driven by durable stage events rather than raw token counts.

Suggested progress stages:

- `upload_saved`
- `parser_started`
- `parser_completed`
- `review_started`
- `review_progress`
- `hitl_waiting`
- `apply_started`
- `apply_completed`
- `completed`
- `failed`

Suggested progress math:

- upload: fixed weight
- parser: fixed weight
- clause review: `reviewed_clauses / total_clauses`
- HITL: `resolved_suggestions / total_suggestions`
- apply: fixed weight

This keeps the progress bar stable even when single LLM calls have unpredictable latency.

## HTML Review Surface

The later planned UI should treat the live annotation/edit experience as an HTML
view, not as raw IR JSON.

Implications:

- the API should expose annotation payloads that are easy to render into HTML highlights
- review state should include enough information to rebuild the same HTML view after pause/resume
- the HTML layer is the primary user-facing review surface even when the backend stores `DocIR`
- native document download remains a separate final artifact step

## Versioned `DocIR` Plan

`WorkflowState` already has version/history concepts, so the API plan should keep them explicit.

Recommended versions:

- `v0`: original upload metadata only
- `v1`: parser output
- `v2+`: accepted human-review decisions applied as logical document revisions
- `final`: verified output after native write-back and re-parse

Persist for each version:

- serialized `DocIR`
- stage name
- reason
- source artifact reference
- created timestamp

## Native Apply Plan

Initial editable formats should be:

- `docx`
- `hwpx`

Apply rules:

- never treat `DocIR` as the native writable document
- use structured edit commands only
- resolve each edit against native source anchors
- apply edits to the original native document
- re-parse the result and verify anchor/text expectations before exposing the download

Formats that should remain suggestion-only for the first API release:

- `pdf`
- any format without safe same-format write-back

PDF note:

- PDF edit/write-back is not implemented today
- the API should still keep parse/review/apply stages separated so PDF edit support can be added soon without reshaping the public workflow

## Storage And Persistence

The API needs more than the current Q&A tables. At minimum, add persistence for:

- review jobs
- suggestion records
- event/progress records
- artifact references
- version records
- checkpoint references

Binary artifacts and serialized `DocIR` blobs should live in file storage or object storage,
with only metadata and pointers in PostgreSQL.

## Rollout Order

1. Align runtimes and package wiring for direct API integration
2. Add upload endpoint, parser execution, and SSE progress stream
3. Add clause-level review suggestions and annotation payloads
4. Add LangGraph pause/resume with human decisions
5. Add native write-back for `docx` and `hwpx`
6. Add PDF suggestion-only handling first, then extend to PDF edit/apply when the parser/write path lands
