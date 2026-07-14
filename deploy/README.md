# Deploy Notes

`docker-compose.yml` is written for Coolify with the project directory set to the repository root. For local validation, include `--project-directory .` from the repo root:

```bash
docker compose --project-directory . --env-file deploy/.env.example -f deploy/docker-compose.yml config
```

## Required Runtime Values

Set these in the deployment environment:

- `DATABASE_URL`
- `EMBEDDING_API_KEY`
- `QDRANT_URL`
- `QDRANT_COLLECTIONS`
- `OPENSEARCH_URL`
- `OPENSEARCH_INDEX`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`
- LLM values for the chosen provider:
  - Gemini: `LLM_PROVIDER=gemini`, `LLM_MODEL`, and `LLM_API_KEY`
  - OpenAI-compatible: `LLM_PROVIDER=openai_compat`, `LLM_MODEL`, `LLM_URL`, and `LLM_API_KEY`

Scoped overrides are optional:

- `QUERY_PARSER_LLM_*` overrides the parser only; otherwise it inherits `LLM_*`.
- `GRAPH_LLM_*` overrides graph planning only; otherwise it inherits `QUERY_PARSER_LLM_*`, then `LLM_*`.

Legacy env names are not passed by `docker-compose.yml` and are not read as runtime fallbacks. Use the names in `deploy/.env.example`.

For the old-to-new environment variable mapping, see
[`env-migration-report.md`](./env-migration-report.md).

Document review artifacts are persisted through:

```env
DOCUMENT_REVIEW_STORAGE_DIR=/app/storage/document_reviews
```

The compose file mounts the `document-review-storage` volume at that path for `backend-api`.
