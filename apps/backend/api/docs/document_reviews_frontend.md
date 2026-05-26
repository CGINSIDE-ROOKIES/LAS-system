# Document Reviews Frontend Integration

This document is the frontend contract for `POST /api/v1/document-reviews` and related endpoints.

## Local Backend Setup

From `apps/backend`:

```bash
cp .env.example .env
cd api
docker compose -f docker-compose.dev.yml up -d postgres
uv sync
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Minimum `.env` values for a real end-to-end document review:

```env
DATABASE_URL=postgresql://las:las@localhost:5432/las
QDRANT_URL=http://<qdrant-host>:6333
QDRANT_COLLECTIONS=law_article,legal_case,legal_relation
OPENSEARCH_URL=http://<opensearch-host>:9200
OPENSEARCH_INDEX=law_article,legal_case,legal_relation
EMBEDDING_API_KEY=<embedding-key>
EMBEDDING_DIMENSIONS=1024
LLM_PROVIDER=gemini
LLM_API_KEY=<gemini-key>
LLM_MODEL=gemini-2.5-flash-lite
NEO4J_URI=bolt://<neo4j-host>:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<neo4j-password>
```

Notes:

- The API startup currently warms RAG, generation, parser, and Neo4j dependencies, so missing RAG/LLM/Neo4j values can stop the backend before document review routes are usable.
- Alembic runs on API startup and creates the `document_review_*` tables.
- Uploaded files and generated previews are stored at `DOCUMENT_REVIEW_STORAGE_DIR`, or `apps/backend/api/storage/document_reviews` by default.

## Local Test Frontend

From `apps/frontend`:

```bash
cp .env.example .env
pnpm install
pnpm dev
```

Set:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
BACKEND_INTERNAL_URL=http://localhost:8000
```

Open:

```text
http://localhost:3000/document-review-test
```

The test page covers upload, SSE events, summary refresh, preview loading, suggestion decisions, resume, apply, and download.

## End-to-End Flow

1. Upload a document with `POST /api/v1/document-reviews`.
2. Connect to `events_url` using `EventSource`.
3. Display `GET /api/v1/document-reviews/{review_id}` as the canonical job state.
4. Render preview in an iframe with `preview.html?kind=latest`.
5. When status is `hitl_waiting`, fetch suggestions.
6. Submit one decision per finding.
7. Call `POST /resume`.
8. If accepted suggestions exist, call `POST /apply`.
9. Show `download_url` after apply completes.

## Create Review

`POST /api/v1/document-reviews`

Request: `multipart/form-data`

- `file`: `.docx`, `.hwpx`, `.hwp`, or `.pdf`
- `options`: optional JSON string

Example options:

```json
{
  "top_k": 8,
  "max_clauses": 10,
  "max_concurrent_risk_reviews": 8,
  "hitl_min_risk_level": "low",
  "doc_types": ["law", "prec", "detc", "decc", "expc"],
  "law_names": ["근로기준법"],
  "include_review_html": true
}
```

Response:

```json
{
  "review_id": "uuid",
  "status": "queued",
  "events_url": "/api/v1/document-reviews/uuid/events"
}
```

## Job Summary

`GET /api/v1/document-reviews/{review_id}`

Important fields:

```ts
type DocumentReviewSummary = {
  review_id: string;
  status: "queued" | "running" | "hitl_waiting" | "applying" | "completed" | "failed";
  stage:
    | "upload_saved"
    | "parser_started"
    | "parser_completed"
    | "review_started"
    | "review_progress"
    | "hitl_waiting"
    | "apply_started"
    | "apply_completed"
    | "completed"
    | "failed";
  progress: number;
  source_name: string;
  source_doc_type: string | null;
  current_preview_kind: "parser" | "risk" | "edited" | null;
  risk_counts: Record<string, number>;
  artifact_flags: Record<string, boolean>;
  preview_url: string;
  events_url: string;
  suggestions_url: string;
  download_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};
```

## Events

`GET /api/v1/document-reviews/{review_id}/events`

Use `EventSource`. Event names:

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

Each event payload is JSON:

```json
{
  "type": "review_progress",
  "seq": 5,
  "timestamp": "2026-05-11T01:23:45.000000+00:00",
  "progress": 0.8,
  "reviewed_clauses": 7,
  "total_clauses": 20,
  "preview_url": "/api/v1/document-reviews/uuid/preview.html?kind=latest"
}
```

Browser helper:

```ts
const es = new EventSource(`${API_BASE}${eventsUrl}`);
for (const name of ["upload_saved", "parser_started", "parser_completed", "review_started", "review_progress", "hitl_waiting", "apply_started", "apply_completed", "completed", "failed"]) {
  es.addEventListener(name, (event) => {
    const payload = JSON.parse((event as MessageEvent).data);
    // refresh summary and preview when needed
  });
}
```

## Preview

`GET /api/v1/document-reviews/{review_id}/preview.html?kind=latest`

Kinds:

- `latest`: current stable preview
- `parser`: parser/category preview
- `risk`: risk annotation preview
- `edited`: edited document preview

Render with:

```tsx
<iframe src={`${API_BASE}${summary.preview_url}`} className="h-full w-full" />
```

## Suggestions

`GET /api/v1/document-reviews/{review_id}/suggestions`

Response:

```ts
type DocumentReviewSuggestion = {
  finding_id: string;
  request_id: string | null;
  clause_id: string | null;
  risk_level: string | null;
  status: "pending" | "accepted" | "rejected" | "feedback";
  title: string;
  kind: string;
  prompt: string;
  guidance: string;
  selected_text: string;
  diff: string | null;
  source_citations: string[];
  proposed_edit: Record<string, unknown> | null;
  allowed_actions: string[];
  payload: Record<string, unknown>;
};
```

Decision:

`POST /api/v1/document-reviews/{review_id}/suggestions/{finding_id}/decision`

```json
{
  "action": "accept",
  "comment": "Looks good"
}
```

Allowed `action`: `accept`, `reject`, `feedback`.

## Resume

`POST /api/v1/document-reviews/{review_id}/resume`

Call this after one or more decisions. The backend resumes LangGraph when the in-process checkpoint is still present, and falls back to the persisted result if needed.

Response:

```json
{
  "review_id": "uuid",
  "status": "running",
  "stage": "review_progress",
  "decisions_applied": 3
}
```

If all decisions reject/feedback and no accepted edits remain, status can become `completed`.

## Apply

`POST /api/v1/document-reviews/{review_id}/apply`

Applies accepted `proposed_edit` payloads to the native document. Only one accepted edit per target is applied; lower-priority target conflicts are returned in `skipped_conflicts`.

Response:

```json
{
  "review_id": "uuid",
  "status": "completed",
  "stage": "completed",
  "edits_applied": 2,
  "skipped_conflicts": [],
  "download_url": "/api/v1/document-reviews/uuid/download",
  "preview_url": "/api/v1/document-reviews/uuid/preview.html?kind=latest",
  "warnings": []
}
```

## Download

`GET /api/v1/document-reviews/{review_id}/download`

Returns the edited native document after apply.

## Frontend State Rules

- Treat `GET /{review_id}` as canonical.
- Use SSE for progress and refresh triggers, not as your only state store.
- Keep showing the latest stable preview while long-running backend work continues.
- Show suggestion actions only while `status === "hitl_waiting"` or suggestions have pending decisions.
- Enable apply only when at least one suggestion has `status === "accepted"` and `proposed_edit != null`.
- Show download only when `download_url` is non-null.
