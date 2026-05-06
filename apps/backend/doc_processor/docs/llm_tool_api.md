# LLM Tool API

This package uses the current upstream `document-processor` API directly.
Except for the local parser entrypoint, calls are keyword-only.

## Entrypoints

- `parse_document(...)`
- `read_document(...)`
- `get_document_context(...)`
- `list_editable_targets(...)`
- `validate_document_edits(...)`
- `apply_document_edits(...)`
- `validate_text_annotations(...)`
- `render_review_html(...)`
- `review_contract_document(...)`
- `review_parsed_contract(...)`

## Parse

```python
from doc_processor import RelevanceMode
from doc_processor.api import parse_document

result = parse_document(
    source_path="tests/doc_samples/new_test/02. 청소년 대중문화예술인 표준 부속합의서.hwpx",
    relevance_mode=RelevanceMode.DISABLED,
    boundary_review_enabled=False,
    label_review_enabled=False,
    include_editable_targets=True,
    max_editable_targets=10,
)
```

`parse_document(...)` returns `ParseDocumentResult`, including compact
paragraph previews, clause summaries, editable targets, and parser warnings.

## Inspect Context

```python
from doc_processor.api import get_document_context

context = get_document_context(
    source_path="sample.docx",
    target_ids=["p_bfa4da5a775f2ffd"],
    before=1,
    after=1,
)
```

## Discover Editable Targets

```python
from doc_processor.api import list_editable_targets

targets = list_editable_targets(
    source_path="sample.docx",
    target_kinds=["paragraph", "run", "cell"],
    only_writable=True,
    max_targets=100,
)
```

Each target includes `current_text` and `text_hash`. Use `text_hash` as the
edit guard.

## Edits

Use upstream `TextEdit`:

```python
from doc_processor.api import TextEdit, apply_document_edits, validate_document_edits

edit = TextEdit(
    target_kind="paragraph",
    target_id="p_bfa4da5a775f2ffd",
    expected_text_hash="0a4d55a8d778e5022fab701977c5d840bbc486d0",
    new_text="Updated paragraph text",
    reason="Clarify obligation",
)

validation = validate_document_edits(source_path="sample.docx", edits=[edit])
if validation.ok:
    result = apply_document_edits(
        source_path="sample.docx",
        edits=[edit],
        output_filename="sample_reviewed.docx",
    )
```

Validation failures return structured `EditValidationIssue` values. A stale
guard returns `text_hash_mismatch` with the current text/hash when available.

Native write-back is currently for `docx`, `hwpx`, and converted `hwp -> hwpx`.
PDF remains review/annotation-only.

## Annotations

```python
from doc_processor.api import TextAnnotation, render_review_html

review = render_review_html(
    source_path="sample.docx",
    annotations=[
        TextAnnotation(
            target_kind="paragraph",
            target_id="p_bfa4da5a775f2ffd",
            selected_text="risky phrase",
            label="High risk",
            color="#FCA5A5",
            note="Source-backed rationale",
        )
    ],
    title="Contract Review",
)
```

`render_review_html(...)` returns `ReviewHtmlResult`; validation failures are
returned in `result.validation`, not raised.

## Contract Review

`review_contract_document(...)` combines parser output, RAG evidence retrieval,
structured generation, annotations, and HITL edit suggestions. It expects
injected clients:

- `RagEvidenceClient.query_legal_db(...)`
- `ReviewGenerationClient.generate(...)`

In `apps/backend/api`, use the existing `get_rag_pipeline()` and
`get_generation_service()` dependencies for those clients.
