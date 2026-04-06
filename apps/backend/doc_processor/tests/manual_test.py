from document_processor import DocIR, export_html
import json
from pathlib import Path

file_name = "251029 2025년 3회 추경 사업설명서(평화협력국)_최종.hwpx"
# "style_test_sample.docx"

doc_dir = Path("/home/maxjo/Work/LAS-system/apps/backend/doc_processor/tests/doc_samples")
out_dir = Path("/home/maxjo/Work/LAS-system/apps/backend/doc_processor/tests/results")

doc_path = Path(doc_dir / file_name)

doc = DocIR.from_file(doc_path)

with \
    open((out_dir / doc_path.stem).with_suffix(".json"), "w", encoding="utf-8") as json_f, \
    open((out_dir / doc_path.stem).with_suffix(".html"), "w", encoding="utf-8") as html_f:
    
    json.dump(doc.model_dump(mode="json"), json_f, indent=4, ensure_ascii=False)
    html_f.write(export_html(doc))

print(f"completed: {doc_path}")
