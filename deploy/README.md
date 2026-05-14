# Deploy Notes

`docker-compose.yml` is written for Coolify with the project directory set to the repository root. For local validation, include `--project-directory .` from the repo root:

```bash
docker compose --project-directory . --env-file deploy/.env.example -f deploy/docker-compose.yml config
```

## Required Runtime Values

Set these in the deployment environment:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `QDRANT_URL`
- `QDRANT_COLLECTIONS`
- `OPENSEARCH_URL`
- `OPENSEARCH_INDEX`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- LLM values for the chosen provider:
  - Gemini: `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL`
  - OpenAI-compatible: `LLM_PROVIDER=openai_compat`, `LLM_MODEL`, `LLM_CHAT_COMPLETIONS_URL`, and `LLM_API_KEY` or `OPENAI_API_KEY`

Document review artifacts are persisted through:

```env
DOCUMENT_REVIEW_STORAGE_DIR=/app/storage/document_reviews
```

The compose file mounts the `document-review-storage` volume at that path for `backend-api`.
