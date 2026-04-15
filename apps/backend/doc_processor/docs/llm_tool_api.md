# LLM Tool API

This package now has a tool-oriented public surface for LLM and agent use.

Use these entrypoints when the caller is producing structured outputs or making
tool calls:

- `parse_document`
- `get_document_context`
- `list_editable_targets`
- `validate_text_edits`
- `apply_text_edits`
- `render_review_html`

The public entrypoints live in [api.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/api.py), and the tool-facing schemas live in [api_types.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/api_types.py). The lower-level native edit engine lives in [edit_engine.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/src/doc_processor/edit_engine.py).

## Why This Surface Exists

The older low-level surface was easy to use from Python, but awkward for LLMs:

- parser entrypoints returned full `WorkflowState`
- edit models were split into `ParagraphTextEdit` and `RunTextEdit`
- annotations inferred target kind from the unit id
- validation failures raised exceptions instead of returning repairable payloads

The new API keeps the same underlying parser/editor logic, but presents a
smaller contract:

- explicit request and response models
- explicit `target_kind`
- exact-text validation through `expected_text`
- structured validation issues with machine-friendly error codes
- compact parse output instead of internal workflow state

## Public Models

### Parse

Request:

- `ParseDocumentRequest`
  - `source_path`
  - `relevance_mode`
  - `boundary_review_enabled`
  - `label_review_enabled`
  - `prompt_profile`
  - `include_paragraphs`
  - `include_clauses`
  - `include_editable_targets`
  - `max_paragraphs`
  - `max_editable_targets`
  - `paragraph_excerpt_length`

Response:

- `ParseDocumentResult`
  - `source_path`
  - `source_doc_type`
  - `accepted`
  - `reason`
  - `relevance`
  - `clause_count`
  - `subclause_count`
  - `paragraphs`
  - `clauses`
  - `editable_targets`
  - `warnings`

### Context And Target Discovery

- `GetDocumentContextRequest`
- `DocumentContextResult`
- `ListEditableTargetsRequest`
- `ListEditableTargetsResult`
- `EditableTarget`

These are intended for the inspect step before an LLM emits edits.

### Edits

Use one edit model only:

```python
class TextEdit(BaseModel):
    target_kind: Literal["paragraph", "run"]
    target_unit_id: str
    expected_text: str
    new_text: str
    reason: str = ""
```

This replaces the need for separate public run and paragraph edit DTOs.

Validation and apply models:

- `ValidateTextEditsRequest`
- `EditValidationResult`
- `EditValidationIssue`
- `ApplyTextEditsRequest`
- `ApplyTextEditsResult`

Validation issue codes:

- `target_not_found`
- `target_kind_mismatch`
- `text_mismatch`
- `mixed_content_not_supported`
- `unsupported_source_doc_type`
- `output_path_conflicts_with_source`

### Annotations

Use one annotation model only:

```python
class TextAnnotation(BaseModel):
    target_kind: Literal["paragraph", "run"]
    target_unit_id: str
    selected_text: str | None = None
    occurrence_index: int | None = None
    label: str
    color: str = "#FFFF00"
    note: str = ""
```

Rules:

- omit `selected_text` to annotate the full target
- if `selected_text` repeats inside the target, set `occurrence_index`
- let the backend resolve canonical `start` / `end` offsets in `ResolvedTextAnnotation`

Models:

- `RenderReviewHtmlRequest`
- `ReviewHtmlResult`
- `ResolvedTextAnnotation`
- `AnnotationValidationResult`
- `AnnotationValidationIssue`

Annotation issue codes:

- `target_not_found`
- `target_kind_mismatch`
- `mixed_content_not_supported`
- `selected_text_not_found`
- `selected_text_ambiguous`
- `occurrence_index_out_of_bounds`

## Design Rules

### 1. `target_kind` is explicit

Do not infer paragraph vs run from the id string. The caller must say which
kind it intends to target.

### 2. `expected_text` is exact for edits, `selected_text` is exact for annotations

Edits remain exact-match guarded.

This is intentional. It prevents stale or ambiguous edits from silently applying
to the wrong content.

If the model only knows a substring, it should first call:

- `get_document_context`
- or `list_editable_targets`

Then use the exact current text from the returned payload.

For annotations, prefer exact `selected_text` inside a known paragraph/run target
instead of asking the model to generate character offsets.

### 3. Validation failures are returned, not thrown

LLMs need repairable failures, not stack traces. The validation/apply surface
returns structured issues with current text when possible.

### 4. `.hwp` write-back becomes `.hwpx`

Native apply supports:

- `docx`
- `hwpx`
- `hwp`

For `.hwp`, the apply path converts to `.hwpx` and writes the edited result as
`.hwpx`.

### 5. Output paths are distinct by default

If `apply_text_edits` is called without `output_path` or `output_filename`, it
uses a sibling `*_edited.*` path by default.

If the caller wants to choose only the file name, use `output_filename`.

If the requested output would overwrite the source file, apply returns a
structured `output_path_conflicts_with_source` issue instead of clobbering the
original file.

## Recommended LLM Workflow

1. Call `parse_document`
2. Choose relevant paragraph or run targets
3. Call `get_document_context` or `list_editable_targets`
4. Build exact `TextEdit` payloads
5. Call `validate_text_edits`
6. If valid, call `apply_text_edits`
7. For review UI, call `render_review_html`

This split is deliberate. It keeps planning, inspection, validation, and native
write-back separate.

## Python Examples

### Parse A Document

```python
from doc_processor import RelevanceMode
from doc_processor.api import ParseDocumentRequest, parse_document

result = parse_document(
    ParseDocumentRequest(
        source_path="tests/doc_samples/new_test/02. 청소년 대중문화예술인 표준 부속합의서.hwpx",
        relevance_mode=RelevanceMode.DISABLED,
        boundary_review_enabled=False,
        label_review_enabled=False,
        include_editable_targets=True,
        max_editable_targets=10,
    )
)

print(result.accepted)
print(result.clause_count)
print(result.paragraphs[0])
print(result.editable_targets[:3])
```

### Inspect Exact Text Before Editing

```python
from doc_processor.api import GetDocumentContextRequest, get_document_context

context = get_document_context(
    GetDocumentContextRequest(
        source_path="sample.docx",
        unit_ids=["s1.p22"],
        before=1,
        after=1,
        include_runs=True,
    )
)

for paragraph in context.paragraphs:
    print(paragraph.unit_id, paragraph.text)
    for run in paragraph.runs:
        print(" ", run.unit_id, repr(run.text))
```

### List Editable Targets

```python
from doc_processor.api import ListEditableTargetsRequest, list_editable_targets

targets = list_editable_targets(
    ListEditableTargetsRequest(
        source_path="sample.docx",
        unit_ids=["s1.p22"],
        target_kinds=["run"],
        include_child_runs=True,
    )
)

for target in targets.targets:
    print(target.target_kind, target.target_unit_id, repr(target.current_text))
```

### Validate Edits

```python
from doc_processor.api import TextEdit, ValidateTextEditsRequest, validate_text_edits

validation = validate_text_edits(
    ValidateTextEditsRequest(
        source_path="sample.docx",
        edits=[
            TextEdit(
                target_kind="paragraph",
                target_unit_id="s1.p22",
                expected_text="① 이 계약의 계약기간은 계약체결일로부터 개시하여, 출판물의 첫 발행일로부터 ___년까지로 한다. ",
                new_text="① 이 계약의 계약기간은 계약체결일로부터 시작하여, 출판물의 첫 발행일로부터 ___년까지로 한다. ",
                reason="용어를 더 자연스럽게 수정",
            )
        ],
    )
)

print(validation.ok)
print(validation.issues)
```

### Apply Edits

```python
from doc_processor.api import ApplyTextEditsRequest, TextEdit, apply_text_edits

result = apply_text_edits(
    ApplyTextEditsRequest(
        source_path="sample.hwp",
        output_filename="sample_review.hwpx",
        edits=[
            TextEdit(
                target_kind="paragraph",
                target_unit_id="s1.p21",
                expected_text="제3조 (계약기간 등)",
                new_text="제3조 (계약 기간 등)",
                reason="표기 통일",
            )
        ],
    )
)

print(result.ok)
print(result.output_path)
print(result.modified_target_ids)
print(result.warnings)
```

### Render Review HTML

```python
from doc_processor.api import RenderReviewHtmlRequest, TextAnnotation, render_review_html

review = render_review_html(
    RenderReviewHtmlRequest(
        source_path="sample.docx",
        title="Review",
        annotations=[
            TextAnnotation(
                target_kind="paragraph",
                target_unit_id="s1.p22",
                selected_text="계약기간",
                label="Risk",
                color="#FFDD88",
                note="Check this clause",
            )
        ],
    )
)

print(review.ok)
print(review.resolved_annotations)
html = review.html
```

## Tool Call JSON Examples

These examples match the request models and are suitable for function calling or
tool invocation payloads.

### `parse_document`

```json
{
  "source_path": "sample.hwpx",
  "relevance_mode": "disabled",
  "boundary_review_enabled": false,
  "label_review_enabled": false,
  "include_paragraphs": true,
  "include_clauses": true,
  "include_editable_targets": true,
  "max_paragraphs": 40,
  "max_editable_targets": 20
}
```

### `get_document_context`

```json
{
  "source_path": "sample.hwpx",
  "unit_ids": ["s1.p22"],
  "before": 1,
  "after": 1,
  "include_runs": true
}
```

### `validate_text_edits`

```json
{
  "source_path": "sample.hwpx",
  "edits": [
    {
      "target_kind": "paragraph",
      "target_unit_id": "s1.p22",
      "expected_text": "① 이 계약의 계약기간은 계약체결일로부터 개시하여, 출판물의 첫 발행일로부터 ___년까지로 한다. ",
      "new_text": "① 이 계약의 계약기간은 계약체결일로부터 시작하여, 출판물의 첫 발행일로부터 ___년까지로 한다. ",
      "reason": "용어 수정"
    }
  ]
}
```

### `apply_text_edits`

```json
{
  "source_path": "sample.hwp",
  "output_filename": "sample_review.hwpx",
  "edits": [
    {
      "target_kind": "paragraph",
      "target_unit_id": "s1.p21",
      "expected_text": "제3조 (계약기간 등)",
      "new_text": "제3조 (계약 기간 등)",
      "reason": "표기 통일"
    }
  ]
}
```

### `render_review_html`

```json
{
  "source_path": "sample.hwpx",
  "title": "Review",
  "annotations": [
    {
      "target_kind": "paragraph",
      "target_unit_id": "s1.p22",
      "selected_text": "계약기간",
      "label": "Risk",
      "color": "#FFDD88",
      "note": "Check this clause"
    }
  ]
}
```

## How To Repair Failed Edits

If validation returns `text_mismatch`:

1. read `current_text` from the issue
2. decide whether the target is still correct
3. rebuild the edit using the returned exact text
4. validate again

If validation returns `target_kind_mismatch`:

1. keep the same `target_unit_id`
2. switch `target_kind` to the correct kind
3. retry validation

If validation returns `mixed_content_not_supported`:

1. do not attempt paragraph-level rewrite
2. inspect child runs with `get_document_context` or `list_editable_targets`
3. emit run-targeted edits instead

If apply returns `output_path_conflicts_with_source`:

1. omit the output fields to use the default sibling `*_edited.*` path
2. or provide a different `output_path`
3. or provide a sibling-only `output_filename`

## Parser-Side Structured Output Tightening

The internal parser review schemas were also tightened to improve structured
model calls:

- boundary review `action` is now a literal enum
- label review `status`, `label`, `candidate_labels`, and split ops are typed
- relevance `doc_kind` is now a literal enum

These changes reduce repair churn when the parser itself is using structured
LLM outputs.

## Tests

See:

- [test_api.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/tests/test_api.py)
- [test_edit_engine.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/tests/test_edit_engine.py)
- [test_annotations.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/tests/test_annotations.py)
- [test_parser.py](/home/maxjo/Work/LAS-system/apps/backend/doc_processor/tests/test_parser.py)
