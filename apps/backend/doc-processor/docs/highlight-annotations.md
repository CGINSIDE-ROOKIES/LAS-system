# Highlight Annotations — LLM → HTML

How to make an LLM highlight parts of a document and render them in HTML.

---

## Overview

```
IRGroup.formatted_str  →  LLM (structured output)  →  ArticleAnnotations
                                                            │
                                                    .resolve(formatted_str)
                                                            │
                                                            ▼
                                                    export_html(..., annotations={idx: ann})
                                                            │
                                                            ▼
                                                    HTML with <mark> tags
```

The LLM receives `formatted_str` (plain text) and returns **exact text matches**
to highlight. The resolver converts those to character offsets internally.
The HTML exporter overlays them as `<mark>` tags at render time.

---

## Models

### `Highlight`

```python
from las_types import Highlight

Highlight(
    text="계약",         # exact text to match in formatted_str
    label="핵심 키워드",   # tooltip text (optional)
    color="#FFD700",      # CSS background color (optional, default yellow)
    occurrence=1,         # which occurrence to highlight (1-based, 0=all)
)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | str | required | Exact text to match in `formatted_str` |
| `label` | str | `""` | Tooltip shown on hover |
| `color` | str | `"#FFFF00"` | CSS hex color |
| `occurrence` | int | `1` | Which match to highlight. `1` = first, `2` = second, `0` = all |

### `ArticleAnnotations`

```python
from las_types import ArticleAnnotations

ann = ArticleAnnotations(
    reasoning="제1조는 목적 조항이며, '계약'이라는 키워드가 핵심입니다.",
    highlights=[
        Highlight(text="제1조", label="조문 번호", color="#90EE90"),
        Highlight(text="계약", label="핵심 키워드", color="#FFD700", occurrence=0),
        Highlight(text="연습생", label="당사자", color="#ADD8E6"),
    ]
)
```

- `reasoning` field is filled first (CoT prompting for better quality)
- `occurrence=0` highlights **all** matches of "계약"
- `occurrence=1` (default) highlights only the **first** match
- Unmatched text is silently skipped (no errors)

---

## LangChain Integration

### As structured output

```python
from las_types import ArticleAnnotations
from pydantic import ValidationError

highlighter_llm = llm.with_structured_output(
    ArticleAnnotations, method="json_mode"
).with_retry(
    retry_if_exception_type=(ValidationError, ValueError),
    stop_after_attempt=3,
)

messages = [
    ("system", "다음 계약 조문을 분석하고, 법적으로 주의가 필요한 부분을 하이라이트하세요."),
    ("user", article.formatted_str),
]
result: ArticleAnnotations = highlighter_llm.invoke(messages)
```

### As a LangGraph node

```python
from las_types import ArticleAnnotations, IRGroupState

def highlight_worker(state: IRGroupState):
    messages = [
        ("system", highlight_prompt),
        ("user", state.ir_group.formatted_str),
    ]
    annotations = highlighter_llm.invoke(messages)
    return {"annotations_temp": [(state.group_idx, annotations)]}
```

### Collecting annotations across groups

```python
# After graph execution, build the annotations dict
# (keyed by group index, matching ir_groups ordering)
annotations: dict[int, ArticleAnnotations] = {
    idx: ann for idx, ann in result["annotations_temp"]
}
```

---

## HTML Export

```python
from core.html_exporter import export_html

html = export_html(
    ir_groups=state.ir_groups,
    style_map=style_map,
    title="법률 검토",
    annotations=annotations,  # dict[group_idx, ArticleAnnotations]
)

Path("reviewed.html").write_text(html, encoding="utf-8")
```

The `annotations` parameter is optional. Groups without annotations
render normally. Resolution (`text` → character offsets) happens
automatically inside `export_html`.

---

## Rendered output

```html
<mark style="background-color:#90EE90;padding:1px 2px;border-radius:2px"
      title="조문 번호">제1조</mark>
```

- `title` shows the label on hover
- Highlights can span across multiple runs (the exporter handles splitting)
- Multiple highlights on the same text are supported

---

## Suggested highlight colors

| Purpose | Color | Hex |
|---------|-------|-----|
| Warning / attention | Yellow | `#FFD700` |
| Legal risk | Red-ish | `#FFB3B3` |
| Key terms | Green | `#90EE90` |
| Reference / link | Blue | `#ADD8E6` |
| Neutral annotation | Gray | `#D3D3D3` |

---

## Text editing (separate from highlights)

Highlights are for **visual annotation only** (HTML export).
To edit the document text, use `edit_assembler.apply_edit()`:

```python
from core.edit_assembler import apply_edit

result = apply_edit(article, edited_text, doc)
# Styles are preserved automatically
```

The two systems are independent: highlights annotate, edits modify.
