from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


import argparse
import json

from src.export.law_corpus_refiner import clean_law_records, enrich_clean_law_records
from src.export.jsonl_builder import write_jsonl


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Build legal_corpus_v2_clean.jsonl from legal_corpus.jsonl")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    report_path = Path(args.report) if args.report else output_path.with_name("law_corpus_clean_report.json")

    records = _read_jsonl(input_path)
    cleaned, report = clean_law_records(records)
    enriched = enrich_clean_law_records(
        cleaned,
        source_file=output_path.name,
        source_base_file=input_path.name,
        corpus_variant="v2_clean",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(enriched, output_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_count": len(enriched), "report_path": str(report_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
