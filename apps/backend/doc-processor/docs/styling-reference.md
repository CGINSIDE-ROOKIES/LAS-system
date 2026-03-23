# Styling Reference — HWPX & DOCX → IR → HTML

How style information flows from source documents through the IR pipeline
to HTML output.

---

## Architecture

```
Source Document (HWPX / DOCX)
    │
    ├──→ IR Pipeline (parser.py → ir.py)     → IRGroup / IRChunk  (text only, LLM-facing)
    │
    └──→ Style Extractor (style_extractor.py) → StyleMap           (formatting, parallel to IR)
                                                    │
                                                    ├── runs:   dict[chunk_id → RunStyleInfo]
                                                    ├── cells:  dict[cell_key → CellStyleInfo]
                                                    └── tables: dict[tbl_root → TableStyleInfo]
                                                    │
                                            ┌───────┘
                                            ▼
                                    HTML Exporter (html_exporter.py)
                                            │
                                            ▼
                                    Styled HTML output
```

Style data lives **outside** the IR — same chunk IDs, separate structure.
The IR stays clean for LLM editing; styles are recombined only at render time.

---

## Run-level text styles

### HWPX source

| Style | Access path | Notes |
|-------|-------------|-------|
| **Bold** | `run.bold` | Direct property |
| **Italic** | `run.italic` | Direct property |
| **Underline** | `run.underline` / `run.style.child_attributes["underline"]["type"]` | Property gives bool; child_attributes gives type (SOLID, DASH, etc.) |
| **Text color** | `run.style.text_color()` / `run.style.attributes["textColor"]` | Hex string `"#RRGGBB"` |
| **Font size** | `run.style.attributes["height"]` | Value in 1/100 pt (e.g. `1300` = 13pt) |
| **Strikethrough** | `run.style.child_attributes["strikeout"]["shape"]` | `"NONE"` = off, anything else = on |
| **Font name** | `run.style.child_attributes["fontRef"]["hangul"]` → header font face table | 2-step: fontRef ID → `<hh:fontface lang="HANGUL"><hh:font id="N" face="...">` |
| **Letter spacing** | `run.style.child_attributes["spacing"]["hangul"]` | Value in relative units |
| **Outline** | `run.style.child_attributes["outline"]["type"]` | `"NONE"` = off |
| **Shadow** | `run.style.child_attributes["shadow"]` | Has `type`, `color`, `offsetX`, `offsetY` |

HWPX style resolution chain:
```
run.char_pr_id_ref = "4"
    → header charPr table → RunStyle object
        → .attributes      = {"height": "1300", "textColor": "#000000", ...}
        → .child_attributes = {"bold": {}, "fontRef": {"hangul": "3", ...}, ...}
            → fontRef["hangul"] = "3" → header fontfaces → face="한컴바탕"
```

### DOCX source

| Style | Access path | Notes |
|-------|-------------|-------|
| **Bold** | `run.bold` | Tri-state: `True`/`False`/`None` (inherit) |
| **Italic** | `run.italic` | Same tri-state |
| **Underline** | `run.underline` | Bool or `WD_UNDERLINE` enum for style variants |
| **Text color** | `run.font.color.rgb` | `RGBColor` object, e.g. `RGBColor(0xFF, 0, 0)` |
| **Font size** | `run.font.size` | In EMU (914400 EMU = 1 inch, 12700 EMU = 1 pt) |
| **Strikethrough** | `run.font.strike` | Bool |
| **Double strike** | `run.font.double_strike` | Bool |
| **Superscript** | `run.font.superscript` | Bool |
| **Subscript** | `run.font.subscript` | Bool |
| **Highlight** | `run.font.highlight_color` | `WD_COLOR_INDEX` enum (limited palette) |
| **All caps** | `run.font.all_caps` | Bool (visual only, not actual text transform) |
| **Font name** | `run.font.name` | Direct string property |

Key difference: DOCX exposes everything as direct properties on `run.font.*`.
Setting `run.text = "..."` preserves the `w:rPr` element (all formatting intact).

### HTML mapping (implemented)

| Style | HTML/CSS | Excluded? |
|-------|----------|-----------|
| Bold | `<b>` | |
| Italic | `<i>` | |
| Underline | `text-decoration: underline` | |
| Strikethrough | `text-decoration: line-through` | |
| Superscript | `<sup>` | |
| Subscript | `<sub>` | |
| Text color | `color: #RRGGBB` | |
| Font size | `font-size: Xpt` | |
| Highlight | `background-color: X` | |
| Font name | — | **Excluded** (cross-platform issues) |
| Letter spacing | — | **Excluded** (rarely needed) |
| Shadow/outline | — | **Excluded** (poor CSS equivalents) |

---

## Table styles

### Cell-level

#### HWPX source

| Style | Access path | Notes |
|-------|-------------|-------|
| **Borders** | `cell.element["borderFillIDRef"]` → header `<hh:borderFill>` | Each side: `<hh:leftBorder type="SOLID" width="0.12 mm" color="#000000">` |
| **Background** | Same borderFill → `<hh:fillBrush faceColor="#RRGGBB">` | Inside the borderFill element |
| **Vertical align** | `cell.element → <hp:subList vertAlign="CENTER">` | Values: `TOP`, `CENTER`, `BOTTOM`, `BASELINE` |
| **Horizontal align** | Cell paragraph `paraPrIDRef` → header `<hh:paraPr>` → `<hh:align horizontal="CENTER">` | Values: `LEFT`, `CENTER`, `RIGHT`, `JUSTIFY`, `DISTRIBUTE` |
| **Merged cells** | `cell.span` → `(rowspan, colspan)` | Also: `tbl.get_cell_map()` gives full grid with anchors |

HWPX border/fill resolution:
```
<hp:tc borderFillIDRef="5">
    → header borderFill id="5"
        → <hh:leftBorder type="SOLID" width="0.12 mm" color="#000000" />
        → <hh:topBorder .../>
        → <hh:fillBrush faceColor="#D9E2F3" />  (if present)
```

#### DOCX source

| Style | Access path | Notes |
|-------|-------------|-------|
| **Borders** | `cell._tc → w:tcPr → w:tcBorders → w:top/bottom/left/right` | Each side: `val` (style), `sz` (1/8 pt), `color` (hex) |
| **Background** | `cell._tc → w:tcPr → w:shd` | `fill` attribute = hex color |
| **Vertical align** | `cell._tc → w:tcPr → w:vAlign` | `val`: `top`, `center`, `bottom` |
| **Horizontal align** | `cell.paragraphs[0].alignment` | Enum: 0=LEFT, 1=CENTER, 2=RIGHT, 3=JUSTIFY |
| **Horizontal merge** | `cell._tc → w:tcPr → w:gridSpan` | `val` = number of columns spanned |
| **Vertical merge** | `cell._tc → w:tcPr → w:vMerge` | `val="restart"` = start; absent val = continuation |

### HTML mapping (implemented)

| Style | HTML/CSS |
|-------|----------|
| Cell borders | `border-top/right/bottom/left: Npx style #color` (per side) |
| Background | `background-color: #RRGGBB` |
| Vertical align | `vertical-align: top/center/bottom` |
| Horizontal align | `text-align: left/center/right/justify` |
| Merged cells | `colspan="N"` / `rowspan="N"` on `<td>` |

---

## Text formatting inside table cells

Same as body text — cells contain paragraphs which contain runs.
The same `RunStyleInfo` extraction applies to cell runs.

```
Table Cell
  └── Paragraph(s)
        └── Run(s)  ← same bold/italic/color/size/etc. as body runs
```

Cell run chunk IDs follow the pattern:
`s1.p{N}.r1.tbl{T}.tr{R}.tc{C}.p{P}.r{R}` — same IDs used in both IR and StyleMap.

---

## Module reference

| Module | Purpose |
|--------|---------|
| `las_types/style_types.py` | `RunStyleInfo`, `CellStyleInfo`, `TableStyleInfo`, `StyleMap` models |
| `core/style_extractor.py` | `extract_styles_hwpx(doc)`, `extract_styles_docx(path)` |
| `core/html_exporter.py` | `export_html(ir_groups, style_map, title=...)` |
