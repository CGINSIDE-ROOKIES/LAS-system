from doc_processor.review_pipeline import review_graph
from doc_processor.las_types import ReviewState, ArticleRiskReport

from pathlib import Path
from typing import cast

file_dirs_std_labor = list(Path("doc_samples/표준계약서모음(hwp-hwpx)").iterdir())
file_dirs_std_contracts = list(Path("doc_samples/(노동)표준근로계약서모음").iterdir())
file_dirs_std_contracts_risks = list(Path("doc_samples/계약서_test_생성본(docx)").iterdir())
file_dirs = file_dirs_std_labor + file_dirs_std_contracts + file_dirs_std_contracts_risks

[print(f"[{i}] {f.name}") for i, f in enumerate(file_dirs)]
sel = int(input("select: "))
file_path = file_dirs[sel]

print(f"\n{'='*60}")
print(f"  Analyzing: {file_path.name}")
print(f"{'='*60}\n")

result = review_graph.invoke(
    input=ReviewState(target_file=Path(file_path)),
    config={"max_concurrency": 4},
)

# --- Write HTML ---
html_path = Path(f"results/{file_path.stem}_risk_review.html")
html_path.parent.mkdir(exist_ok=True)
with open(html_path, "w", encoding="utf-8") as f:
    f.write(result["html_output"])
print(f"\nHTML written to: {html_path}")

# --- Print risk summary ---
print(f"\n{'='*60}")
print("  RISK SUMMARY")
print(f"{'='*60}")

risk_reports: list[ArticleRiskReport] = result.get("risk_reports", [])
if not risk_reports or all(len(r.risks) == 0 for r in risk_reports):
    print("\n  리스크가 발견되지 않았습니다.\n")
else:
    for report in risk_reports:
        report = cast(ArticleRiskReport, report)
        if not report.risks:
            continue
        print(f"\n  [제{report.article_n}조]")
        for risk in report.risks:
            print(f"    [{risk.severity.upper():6s}] {risk.risk_type}")
            print(f"           {risk.explanation}")
            if risk.legal_basis:
                print(f"           근거: {risk.legal_basis}")
            print(f"           텍스트: \"{risk.clause_text[:60]}{'...' if len(risk.clause_text) > 60 else ''}\"")

total_risks = sum(len(r.risks) for r in risk_reports)
high = sum(1 for r in risk_reports for risk in r.risks if risk.severity == "high")
medium = sum(1 for r in risk_reports for risk in r.risks if risk.severity == "medium")
low = sum(1 for r in risk_reports for risk in r.risks if risk.severity == "low")

print(f"\n  Total: {total_risks} risks (high={high}, medium={medium}, low={low})")
print(f"\n  ⚠ {risk_reports[0].disclaimer if risk_reports else '본 분석은 AI 참고의견이며, 법적 효력이 없습니다.'}")
print()
