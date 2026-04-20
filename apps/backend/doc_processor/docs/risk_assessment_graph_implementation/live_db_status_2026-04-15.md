# Live DB Status Snapshot

Date: 2026-04-15 UTC

Purpose: current runtime snapshot for the legal retrieval databases, captured after the earlier April 14 reports.

Related docs:

- [LAS_risk_assessment_plan.md](/home/cg-rookies/LAS_risk_assessment_plan.md:1)
- [rag_qdrant_opensearch_investigation_report_2026-04-14.md](/home/cg-rookies/rag_qdrant_opensearch_investigation_report_2026-04-14.md:1)
- [rag_trace_78ebfb23_overlap_report_2026-04-14.md](/home/cg-rookies/rag_trace_78ebfb23_overlap_report_2026-04-14.md:1)

## Runtime Containers

Relevant running containers at capture time:

- `backend-api-ussahlda4xt04kllmn11dn2t-001445493985`
- `law-updater-ussahlda4xt04kllmn11dn2t-001445508772`
- `opensearch-qq82lzpyb7t6qcmk6e0lkk88`
- `qdrant-qhepejgiqexcpwgibixh2rho`

## Effective Search Config

Observed from running container environment:

- `QDRANT_URL=http://qdrant-qhepejgiqexcpwgibixh2rho:6333`
- `QDRANT_COLLECTIONS=law_article,legal_case,legal_relation`
- `QDRANT_VECTOR_NAME_MAP=law_article=body`
- `OPENSEARCH_URL=http://opensearch-qq82lzpyb7t6qcmk6e0lkk88:9200`
- `OPENSEARCH_INDEX=law_article,legal_case,legal_relation`
- `EMBEDDING_MODEL=text-embedding-3-large`
- `OPENAI_EMBEDDING_DIMENSIONS=1024`

Interpretation:

- runtime is still configured to search all 3 corpora on both backends
- runtime still uses only the `body` named vector for `law_article`
- runtime still assumes `text-embedding-3-large` with 1024 dimensions

## Current Corpus Counts

### Qdrant

- `law_article`
  - `points_count=1982`
  - `indexed_vectors_count=0`
  - named vectors: `body`, `appendix`
- `legal_case`
  - `points_count=73690`
  - `indexed_vectors_count=73690`
  - single vector, size `1024`
- `legal_relation`
  - `points_count=18461`
  - `indexed_vectors_count=0`
  - single vector, size `1024`

### OpenSearch

- `law_article`
  - `count=1982`
- `legal_case`
  - `count=73690`
- `legal_relation`
  - `count=18461`

Interpretation:

- the severe April 14 `legal_relation` count mismatch is no longer present
- `legal_relation` is now aligned in count across both backends
- however, Qdrant metadata currently reports `indexed_vectors_count=0` for `law_article` and `legal_relation`
- that does not by itself prove those collections are unusable, but it is a runtime fact worth verifying before relying on dense retrieval there

## `legal_relation` Distribution

OpenSearch aggregation on `legal_relation`:

- `relation_model`
  - `case_to_case = 10165`
  - `law_to_case = 7176`
  - `law_to_law = 1120`
- `retrieval_role`
  - `trace = 10165`
  - `expansion = 7176`
  - `linkage = 1120`
- `relation_model_priority`
  - `secondary = 10165`
  - `primary = 8296`

Interpretation:

- `legal_relation` is not a clean primary-evidence corpus
- the largest bucket is still `case_to_case` plus `trace`
- if used at all, it should be treated as expansion/linkage support, not first-pass evidence

## Field Availability

Observed OpenSearch fields:

- `law_article`
  - `id`, `doc_type`, `law_name`, `article_no_display`, `root_law_name`, `related_law_name`, `related_law_names`, `search_text`, `text`
- `legal_case`
  - `id`, `doc_type`, `law_name`, `root_law_name`, `related_law_name`, `related_law_names`, `search_text`, `text`
- `legal_relation`
  - `id`, `doc_type`, `law_name`, `article_no_display`, `relation_model`, `relation_type`, `retrieval_role`, `default_score_multiplier`, `relation_model_priority`, `root_law_name`, `related_law_name`, `related_law_names`, `search_text`, `text`

Observed `legal_relation` field types in OpenSearch:

- `relation_model: keyword`
- `relation_type: keyword`
- `retrieval_role: keyword`
- `default_score_multiplier: float`
- `relation_model_priority: keyword`
- `related_law_names: keyword`

Interpretation:

- the metadata needed for strict role-based filtering is available
- unlike the old `/rag` runtime, the new module can actually use `retrieval_role`, `relation_model`, and `relation_model_priority`

## Sample Payload Observations

### `law_article`

Observed samples are clean statute rows:

- explicit `law_name`
- explicit `article_no_display`
- `doc_type=law`
- `root_law_name` present

This supports:

- exact article matching
- law-first retrieval
- explicit citation output

### `legal_case`

Observed samples still show broad related-law metadata.

Example pattern:

- `root_law_name=근로기준법`
- `related_law_names` contains many laws including `근로자퇴직급여 보장법`
- long `search_text` and `text` payloads include case body material

Interpretation:

- `related_law_names` is still too broad to use as a strict normative admission rule
- case retrieval should prefer `root_law_name` and stricter post-filtering

### `legal_relation`

Observed samples include mixed roles:

- `law_to_case` with `retrieval_role=expansion`
- `case_to_case` with `retrieval_role=trace`

Interpretation:

- `law_to_case` expansion rows may be useful for secondary support
- `case_to_case` trace rows should not be allowed into primary evidence by default

## Live Behavior Check

Using OpenSearch BM25 on the question:

- `퇴직급여는 어떻게 받을 수 있지 근거랑`

Observed behavior:

- `law_article` returns direct statutes, including `근로자퇴직급여 보장법` articles
- `legal_case` still returns multiple highly similar `detc` chunks first
- `legal_relation` returns generic relation snippets rather than direct legal authority

Interpretation:

- the old precision problem is still present
- law-first retrieval is still necessary even after the corpus count mismatch was reduced
- near-duplicate case suppression is still required

## Design Implications For The New Assessment Module

Recommended retrieval policy based on current live state:

- `law_article`
  - primary evidence
  - always first
  - use exact article matching where possible
  - support both `body` and `appendix` search paths when annex cues exist
- `legal_case`
  - secondary support only
  - cap final selected case chunks
  - apply near-duplicate suppression
  - prefer `root_law_name` matches over broad `related_law_names`
- `legal_relation`
  - off by default in v1
  - if enabled, restrict to `law_to_case` or `law_to_law`
  - exclude `case_to_case` and `retrieval_role=trace` by default

## Practical Conclusion

The current DB state is better than the April 14 snapshot in one important way:

- `legal_relation` counts are now aligned across Qdrant and OpenSearch

But the main retrieval-quality risks still remain:

- law-first behavior is still not guaranteed by the current system
- case metadata is still broad enough to admit irrelevant or repetitive case chunks
- relation rows are still mixed-purpose and should not be treated as primary evidence
- near-duplicate suppression is still required

This supports the revised assessment plan:

- independent retrieval subsystem
- law-first staged retrieval
- exact article usage
- hard filtering
- diversity control
- `legal_relation` treated as optional enrichment only
