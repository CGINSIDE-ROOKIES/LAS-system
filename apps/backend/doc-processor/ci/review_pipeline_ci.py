"""Non-interactive review pipeline test for CI / container usage.

Usage:
    python -m ci.review_pipeline_ci path/to/document.hwpx
    python -m ci.review_pipeline_ci --smoke   # import-only smoke test
"""

import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python -m tests.review_pipeline_ci <file_path | --smoke>")
    sys.exit(1)

if sys.argv[1] == "--smoke":
    from doc_processor.review_pipeline import review_graph  # noqa: F401
    from doc_processor.las_types import ReviewState  # noqa: F401
    print("Smoke test passed: all imports OK")
    sys.exit(0)

file_path = Path(sys.argv[1])
if not file_path.exists():
    print(f"File not found: {file_path}")
    sys.exit(1)

from doc_processor.review_pipeline import review_graph
from doc_processor.las_types import ReviewState, ArticleRiskReport
from typing import cast

print(f"\n{'='*60}")
print(f"  Analyzing: {file_path.name}")
print(f"{'='*60}\n")

result = review_graph.invoke(
    input=ReviewState(target_file=file_path),
    config={"max_concurrency": 4},
)

# --- Write HTML ---
html_path = Path(f"results/{file_path.stem}_risk_review.html")
html_path.parent.mkdir(exist_ok=True)
with open(html_path, "w", encoding="utf-8") as f:
    f.write(result["html_output"])
print(f"HTML written to: {html_path}")

# --- Print risk summary ---
risk_reports: list[ArticleRiskReport] = result.get("risk_reports", [])
total_risks = sum(len(r.risks) for r in risk_reports)
high = sum(1 for r in risk_reports for risk in r.risks if risk.severity == "high")
medium = sum(1 for r in risk_reports for risk in r.risks if risk.severity == "medium")
low = sum(1 for r in risk_reports for risk in r.risks if risk.severity == "low")

print(f"\nTotal: {total_risks} risks (high={high}, medium={medium}, low={low})")
