# Contract Review RAG Flow

This note defines the current backend direction for source-backed contract
review. The implementation entrypoints are:

- `review_contract_document(...)`
- `review_parsed_contract(...)`
- models in `doc_processor.contract_review`

## Document Processor API

`document-processor` is now sourced from upstream `main`.

The local package now follows the new upstream API directly:

- context/render/edit functions are keyword-only
- text edits use `TextEdit(expected_text_hash=...)`
- edit application uses `validate_document_edits(...)` and
  `apply_document_edits(...)`
- legacy `doc_processor.edit_engine`, `doc_processor.annotations`,
  `validate_text_edits(...)`, and `apply_text_edits(...)` wrappers are removed

`parse_document(...)` remains a local parser entrypoint, but it also uses
keyword-only arguments to match the new calling style.

## RAG Review Boundary

`doc_processor.contract_review` depends on protocols instead of concrete API
services:

- `RagEvidenceClient.query_legal_db(...)`
- `ReviewGenerationClient.generate(...)`

In `apps/backend/api`, these should be provided by existing dependencies:

- `get_rag_pipeline()` for retrieval evidence
- `get_generation_service()` for structured finding generation

This keeps the dependency direction simple:

- `api` orchestrates request/session/storage
- `doc_processor` parses, anchors, annotates, and builds edit DTOs
- `rag` retrieves legal evidence and generates source-grounded review text

## Clause Review Loop

1. Parse the uploaded document with `parse_document(...)`.
2. Build clause-scoped review units from `ClauseSummary.member_node_ids`.
3. For each clause, call `RagPipeline.query_legal_db(...)` with
   `intent="normative"` and the clause text as `search_query`.
4. Send the clause text plus RAG evidence to the generation client.
5. Require strict JSON findings:
   - severity
   - issue type
   - target paragraph node id
   - risky selected text
   - rationale grounded in `source_ids`
   - recommendation
   - optional replacement text
6. Convert findings into:
   - `TextAnnotation` for HTML preview highlights
   - source list for auditability
   - exact-text `TextEdit` suggestions for HITL acceptance
7. Render optional review HTML with `render_review_html(...)`.

The clause boundary is the context-control unit. This follows the same design
principle as hierarchical long-document editors: local edits should be scoped
to a structural node, while the system can still expose higher-level progress
and navigation.

## HITL State Flow

Suggested suggestion states:

- `pending`
- `accepted`
- `rejected`
- `feedback`

Suggested document review stages:

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

Feedback should regenerate only the affected suggestion or clause. Accepted
suggestions become `TextEdit` commands. Rejected suggestions are retained for
audit but excluded from apply.

## API Endpoint Shape

Add a dedicated router in `apps/backend/api`, for example
`src/routers/document_reviews.py`, mounted at `/api/v1/document-reviews`.

Recommended endpoints:

- `POST /api/v1/document-reviews`
  - multipart upload
  - create review id
  - save original
  - start parse/review job

- `GET /api/v1/document-reviews/{review_id}`
  - status, progress, parsed clause count, suggestion counts, artifact flags

- `GET /api/v1/document-reviews/{review_id}/events`
  - SSE progress events

- `GET /api/v1/document-reviews/{review_id}/suggestions`
  - unresolved and resolved findings with severity, sources, annotations,
    recommendations, and proposed edits

- `POST /api/v1/document-reviews/{review_id}/suggestions/{suggestion_id}/decision`
  - body: `{"decision":"accept|reject|feedback","feedback": "..."}`

- `POST /api/v1/document-reviews/{review_id}/resume`
  - continue after HITL decisions or feedback regeneration

- `GET /api/v1/document-reviews/{review_id}/preview.html`
  - latest review HTML generated from annotations

- `POST /api/v1/document-reviews/{review_id}/apply`
  - validate accepted edits
  - apply to native source for editable formats
  - re-parse edited artifact

- `GET /api/v1/document-reviews/{review_id}/download`
  - return edited native artifact when available

Initial native write-back should stay limited to `docx`, `hwpx`, and converted
`hwp -> hwpx`. PDF should remain review/annotation-only until native PDF
editing is explicitly implemented.

## Design References

- TreeWriter, arXiv:2601.12740: use document hierarchy to control context,
  navigation, and edit scope.
- InkSync, arXiv:2309.15337: separate executable suggestions from human
  acceptance, and keep verification/audit evidence attached to generated edits.
