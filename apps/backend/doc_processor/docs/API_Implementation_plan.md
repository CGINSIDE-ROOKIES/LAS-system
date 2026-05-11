Implementation Plan

I would like to implement where:
1. parse
2. categorize/label
3. analysis w/ RAG
4. HITL / accept or reject edit suggestions
5. choose to download the edited doc
(6). all with constant preview for each step available
can be implemented into an api endpoint in apps/backend/api so that it can be used in the frontend


Use doc_processor.contract_review as the engine and add an API orchestration layer in apps/backend/api. Do not put API/session/
storage logic into doc_processor.

Current useful primitives already exist:

- Parse/category: parse_document(...) in doc_processor.api
- Review graph: build_contract_review_graph(...) in doc_processor.contract_review
- RAG evidence: RagPipeline.query_legal_db(...)
- HITL pause/resume: LangGraph interrupt(...) + Command(resume=...)
- Native apply: apply_document_edits(...)
- Preview HTML: render_review_html(...)

1. Package Wiring

Update apps/backend/api/pyproject.toml:

dependencies = [
...
"doc-processor",
"python-multipart",
]

[tool.uv.sources]
doc-processor = { path = "../doc_processor", editable = true }

Keep RAG dependencies as-is. API already has get_rag_pipeline() and get_generation_service() in apps/backend/api/src/
dependencies.py:34, which match the RagEvidenceClient / ReviewGenerationClient protocols.

2. Add API Modules

Add:

apps/backend/api/src/document_reviews/
models.py        # API request/response DTOs
storage.py       # artifact paths + DB persistence helpers
service.py       # orchestration around doc_processor graph
previews.py      # parser/risk/edited preview builders

Add router:

apps/backend/api/src/routers/document_reviews.py

Mount in apps/backend/api/main.py:184:

app.include_router(document_reviews.router, prefix="/api/v1/document-reviews")

3. Persistent Job Model

Add Alembic migration for:

- document_review_jobs
- id
- status: queued|running|hitl_waiting|applying|completed|failed
- stage: upload_saved|parser_started|parser_completed|review_started|review_progress|hitl_waiting|apply_started|
apply_completed|completed|failed
- source_name, source_doc_type
- original_artifact_path
- edited_artifact_path
- parser_result JSONB
- contract_review_result JSONB
- current_preview_kind
- error
- timestamps
- document_review_events
- review_id
- seq
- stage
- payload JSONB
- timestamp
- document_review_suggestions
- review_id
- finding_id
- clause_id
- risk_level
- status
- payload JSONB
- proposed_edit JSONB
- document_review_artifacts
- review_id
- kind: original|parser_preview|risk_preview|edited|edited_preview
- path
- content_type

Store files under something like:

$DOCUMENT_REVIEW_STORAGE_DIR/{review_id}/
original.docx
parser_preview.html
risk_preview.html
edited.docx
edited_preview.html

4. Endpoint Shape

Implement:

POST /api/v1/document-reviews

Multipart upload + options. Creates job, saves original, starts background workflow, returns:

{
"review_id": "...",
"status": "queued",
"events_url": "/api/v1/document-reviews/{id}/events"
}

GET /api/v1/document-reviews/{review_id}

Returns current job summary, stage, progress, risk counts, artifact flags, and preview URLs.

GET /api/v1/document-reviews/{review_id}/events

SSE stream. Frontend uses this for constant progress and preview refresh.

GET /api/v1/document-reviews/{review_id}/preview.html?kind=parser|risk|edited|latest

Returns current HTML preview.

GET /api/v1/document-reviews/{review_id}/suggestions

Returns findings/HITL requests with source citations, proposed edits, status.

POST /api/v1/document-reviews/{review_id}/suggestions/{finding_id}/decision

Accept/reject/feedback one suggestion.

POST /api/v1/document-reviews/{review_id}/resume

Resumes LangGraph HITL with accumulated decisions.

POST /api/v1/document-reviews/{review_id}/apply

Applies accepted edits, generates edited preview.

GET /api/v1/document-reviews/{review_id}/download

Returns edited native document if available.

5. Workflow Mapping

API job runner should do:

1. Save upload.
2. Emit upload_saved.
3. Parse/category using parse_document(...) or the graph’s load_and_categorize_contract.
4. Save ParseDocumentResult.
5. Build parser-category annotations like the notebook does, but move that logic into previews.py.
6. Render parser_preview.html.
7. Emit parser_completed with preview URL.
8. Build contract review graph:

graph = build_contract_review_graph(checkpointer=...)

Use config:

{
"configurable": {
"thread_id": review_id,
"rag_client": get_rag_pipeline(),
"generation_client": get_generation_service(),
},
"max_concurrency": request.max_concurrent_risk_reviews,
}

9. Run review with pause_for_hitl=True.
10. On interrupt, persist HITL requests and emit hitl_waiting.
11. Frontend accepts/rejects/feedbacks suggestions.
12. Resume graph with:

Command(resume={"decisions": decisions})

13. Persist final statuses.
14. On apply request, collect accepted TextEdits, resolve conflicts per target, call apply_document_edits(...).
15. Render edited_preview.html.
16. Expose download.

6. Preview Strategy

To satisfy “constant preview for each step”:

- After upload: original preview, no annotations.
- After parse/category: parser category annotations.
- During RAG analysis: update progress per reviewed clause; latest stable preview remains parser preview until risk preview
exists.
- After risk analysis: risk finding annotations from ContractReviewResult.review_html.
- During HITL: same risk preview, but suggestions list/status updates live.
- After apply: edited document preview with “수정됨” annotations.
- After download available: final edited preview + download URL.

Frontend only needs to poll/SSE job state and load preview.html?kind=latest.

7. Important Implementation Notes

Do not use review_contract_document(...) directly for the API HITL path, because it builds an uncheckpointed graph internally.
Use build_contract_review_graph(checkpointer=...) with a stable thread_id.

Right now only InMemorySaver is installed. For a real API, either add langgraph-checkpoint-postgres or persist enough graph/job
state yourself. Since API already has Postgres, I’d add a real persistent checkpointer rather than rely on process memory.

For v1, keep background execution in-process if needed, but design the DB/events/artifacts so it can move to a worker later
without changing frontend contracts.

===

extras

1. Progress For LLM Steps

For LLM-backed steps, don’t make the frontend infer progress from request duration. Emit durable stage events from the backend.

Use weighted progress:

upload_saved          5%
parser_started        10%
parser_progress       10-35%
parser_completed      35%
review_started        40%
review_progress       40-80%
hitl_waiting          80%
apply_started         85%
apply_completed       95%
completed             100%
failed                terminal

Parser/categorization progress can be based on known units:

- total paragraphs
- boundary suspects reviewed
- ambiguous labels reviewed
- parser graph node completed

Risk analysis progress is easier:

reviewed_clauses / total_clauses

contract_review.py already creates review_units from clauses and runs one risk_review_worker per unit, so the API service can
emit:

{
"stage": "review_progress",
"reviewed_clauses": 7,
"total_clauses": 20,
"progress": 0.54
}

For categorization, if exact paragraph-level progress is hard at first, v1 can emit coarse graph-node progress:

parser_started
parser_relevance_checked
parser_regex_completed
parser_llm_review_started
parser_completed

Then refine later by instrumenting parser nodes.

2. HITL Cards

Yes. The HITL card rendering from doc_processor_categorization_demo.ipynb should be implemented in the frontend.

Backend should return structured card data only:

{
"finding_id": "...",
"risk_level": "high",
"title": "위약금 예정 조항",
"kind": "suggested_edit",
"prompt": "제안된 수정안을 적용하기 전에 검토하세요.",
"guidance": "...",
"selected_text": "...",
"diff": "--- current\n+++ suggested\n...",
"source_citations": ["근로기준법 제20조 (law-1)"],
"proposed_edit": {...},
"allowed_actions": ["accept", "reject", "feedback"]
}

The frontend owns:

- card layout
- colors/badges
- diff rendering
- accept/reject/feedback buttons
- grouping by clause/risk level
- filters/sorting

Backend owns:

- stable IDs
- status
- legal evidence/citations
- proposed edit payload
- validation
- applying accepted edits

So the notebook’s HTML/card helpers are a UX reference, not backend API output. The only backend HTML endpoint I’d keep is
document preview HTML from render_review_html(...), because that preview depends on document parsing/annotation resolution.