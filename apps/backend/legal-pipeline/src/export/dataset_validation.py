from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from src.common.io_utils import _iter_jsonl, _write_json


def _is_article_row(row: dict[str, Any]) -> bool:
    return row.get("doc_type") == "law" and row.get("section_type") == "article"


def validate_appendix_merge_outputs(
    *,
    output_dir: str | Path,
    manifest_path: str | Path,
    dataset_manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    manifest_path = Path(manifest_path)

    article_appendix_manifest = dataset_manifest.get("article_appendix_manifest")
    checks: list[dict[str, str]] = []

    if not isinstance(article_appendix_manifest, dict):
        checks.append({"name": "article_appendix_manifest_present", "status": "failed"})
        summary = {
            "generated_by": "validate_appendix_merge_outputs",
            "validated_at": datetime.now(UTC).date().isoformat(),
            "output_dir": str(output_dir),
            "checks": checks,
            "dataset_manifest": dataset_manifest,
        }
        _write_json(manifest_path, summary)
        raise RuntimeError("Appendix merge validation failed: article_appendix_manifest is missing")

    checks.append({"name": "article_appendix_manifest_present", "status": "passed"})

    legal_corpus_path = output_dir / "legal_corpus.jsonl"
    saw_appendix_fields = False
    saw_linked_appendix_row = False

    for row in _iter_jsonl(legal_corpus_path):
        if not _is_article_row(row):
            continue

        if "has_related_appendix" in row and "related_appendices" in row and "appendix_vector_text" in row:
            saw_appendix_fields = True

        if bool(row.get("has_related_appendix")):
            saw_linked_appendix_row = True

        if saw_appendix_fields and saw_linked_appendix_row:
            break

    checks.append(
        {
            "name": "legal_corpus_contains_appendix_fields",
            "status": "passed" if saw_appendix_fields else "failed",
        }
    )
    checks.append(
        {
            "name": "legal_corpus_contains_linked_appendix_rows",
            "status": "passed" if saw_linked_appendix_row else "failed",
        }
    )

    summary = {
        "generated_by": "validate_appendix_merge_outputs",
        "validated_at": datetime.now(UTC).date().isoformat(),
        "output_dir": str(output_dir),
        "dataset_manifest": {
            "legal_corpus_count": dataset_manifest.get("legal_corpus_count"),
            "law_record_count": dataset_manifest.get("law_record_count"),
            "related_doc_record_count": dataset_manifest.get("related_doc_record_count"),
            "article_appendix_manifest": article_appendix_manifest,
        },
        "checks": checks,
    }
    _write_json(manifest_path, summary)

    failed_checks = [item["name"] for item in checks if item["status"] != "passed"]
    if failed_checks:
        joined = ", ".join(failed_checks)
        raise RuntimeError(f"Appendix merge validation failed: {joined}")

    return summary
