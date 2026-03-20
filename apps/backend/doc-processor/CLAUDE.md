# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Document processing pipeline for Korean legal contracts (HWPX/DOCX/HWP). Parses documents into an intermediate representation (IR), classifies articles via LLM, supports styled HTML export with highlight annotations, and diff-based text editing that preserves run-level formatting.

## Commands

```bash
uv sync                          # install deps
uv sync --extra intel             # with OpenVINO optimization
python -m tests.edit_assembler_test  # round-trip edit test (HWPX + DOCX → HTML)
```

No pytest — tests are standalone scripts in `tests/` run with `python -m`.

## Pipeline (LangGraph)

```
Document (HWPX/DOCX/HWP)
  → DocumentState.from_file()           # parse into IR
  → parser_graph (LangGraph StateGraph)  # LLM classification
      ├─ prelim_categorization_workers   # skip non-articles (article_n == "-1")
      └─ categorization_workers          # 5-category: 제목/전문/조문/입력란/기타
  → edit_assembler.apply_edit()          # diff-based text editing
  → html_exporter.export_html()          # styled HTML + highlight annotations
```

## Two-level IR model

- **IRChunk** — maps 1:1 to a document run (smallest formatting unit). ID scheme: `s1.p3.r2` (body) or `s1.p1.r1.tbl1.tr2.tc3.p1.r1` (table cell).
- **IRGroup** — groups chunks into one article. `formatted_str` is the text the LLM sees. `run_spans()` maps character offsets back to chunks.

Style information lives in a separate parallel `StyleMap` (not in the IR) — recombined only at render time.

## Key modules (`doc_processor/`)

| Module | Purpose |
|--------|---------|
| `parser.py` | LangGraph graph definition & document loading |
| `llms.py` | LLM client registry (midm, GPT-5 Nano, Gemini Flash Lite) |
| `core/ir.py` | IR construction, article number extraction, `ir_grouper` |
| `core/docx_ir.py` | DOCX → IR conversion (mirrors HWPX ID scheme) |
| `core/edit_assembler.py` | Diff-based run editing — preserves per-run styles |
| `core/style_extractor.py` | Extract `StyleMap` from HWPX XML or DOCX properties |
| `core/html_exporter.py` | Render IR + StyleMap → HTML with inline CSS, table merging, `<mark>` highlights |
| `las_types/` | All Pydantic models (IR, state, style, annotations) — exports from `__init__.py` |
| `prompts/` | LLM prompt `.txt` files loaded dynamically via `prompts.py` |

## Two independent output systems

- **Highlights** — visual-only `<mark>` tags in HTML. LLM returns `ArticleAnnotations` (structured output) with exact text matches + `occurrence` field. `resolve()` converts to char offsets at render time.
- **Edits** — modify actual document text via `edit_assembler.apply_edit()`. Uses difflib to map `formatted_str` changes back to document runs, preserving `charPrIDRef` styling. Tables are read-only.

## Style handling

HWPX styles require multi-step XML lookups (`charPrIDRef` → style attributes → font face table; `borderFillIDRef` → border/fill XML with `hc:` namespace). DOCX styles come from python-docx properties. Both produce the same `StyleMap` keyed by chunk IDs.

## Dependencies of note

- `python-hwpx` — custom HWPX parser (git: `github.com/maxjo0418/python-hwpx.git`, not on PyPI)
- `jpype1` — Java bridge for HWP→HWPX conversion via bundled JAR in `vendor/hwp2hwpx/`
- Python `==3.12.*` required
