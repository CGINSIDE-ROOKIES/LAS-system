from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.io_utils import _iter_jsonl, _safe_filename, _write_json, _write_jsonl
from src.export.legal_relation_builder import build_root_relation_payloads



def get_relation_rules(
    scope: dict[str, Any],
    file_id: str = "03_expanded_related_docs",
) -> list[str]:
    outputs = scope.get("outputs", [])
    if not isinstance(outputs, list):
        return ["related_law", "cited_law", "cited_case", "referenced_interpretation"]

    for output in outputs:
        if isinstance(output, dict) and output.get("file_id") == file_id:
            rules = output.get("relation_rules", [])
            if isinstance(rules, list) and rules:
                return [str(rule) for rule in rules]

    return ["related_law", "cited_law", "cited_case", "referenced_interpretation"]



def get_family_law_names(family_result: dict[str, Any]) -> list[str]:
    laws = family_result.get("laws", [])
    if not isinstance(laws, list):
        raise ValueError("family_result.laws must be a list")

    names: list[str] = []
    seen: set[str] = set()

    for law in laws:
        if not isinstance(law, dict):
            continue

        law_name = str(law.get("law_name") or "").strip()
        if not law_name or law_name in seen:
            continue

        seen.add(law_name)
        names.append(law_name)

    return names



def _load_root_candidate_hits(raw_root_dir: Path) -> list[dict[str, Any]]:
    return list(_iter_jsonl(raw_root_dir / "candidate_hits.jsonl"))



def _load_root_canonical_cases(raw_root_dir: Path) -> list[dict[str, Any]]:
    return list(_iter_jsonl(raw_root_dir / "canonical_cases.jsonl"))



def collect_expanded_related_docs_for_family_result(
    scope: dict[str, Any],
    family_result: dict[str, Any],
    raw_related_base_dir: str | Path = "data/raw/02_related_legal_docs",
    save_dir: str | Path = "data/expanded/03_expanded_related_docs",
    targets: list[str] | None = None,
    max_records_per_target: int = 50,
) -> dict[str, Any]:
    root_law_name = str(family_result.get("root_law_name") or "").strip()
    if not root_law_name:
        raise ValueError("family_result.root_law_name is required")

    family_law_names = get_family_law_names(family_result)
    relation_rules = get_relation_rules(scope)

    raw_root_dir = Path(raw_related_base_dir) / _safe_filename(root_law_name)
    save_root_dir = Path(save_dir) / _safe_filename(root_law_name)

    candidate_hits = _load_root_candidate_hits(raw_root_dir)
    canonical_case_rows = _load_root_canonical_cases(raw_root_dir)

    all_records = build_root_relation_payloads(
        root_law_name=root_law_name,
        candidate_hits=candidate_hits,
        canonical_case_rows=canonical_case_rows,
        relation_rules=relation_rules,
        targets=targets,
    )

    per_target_records: dict[str, list[dict[str, Any]]] = {}
    for record in all_records:
        target = str(record.get("target") or "").strip()
        per_target_records.setdefault(target, []).append(record)

    result = {
        "root_law_name": root_law_name,
        "family_law_names": family_law_names,
        "relation_rules": relation_rules,
        "targets": {},
        "expanded_count": 0,
        "records": [],
        "errors": [],
    }

    written_records: list[dict[str, Any]] = []

    for target, rows in sorted(per_target_records.items()):
        selected_rows = rows[:max_records_per_target]
        target_dir = save_root_dir / target
        for row in selected_rows:
            law_uid = str(row.get("law_uid") or "unknown-law")
            canonical_case_id = str(row.get("canonical_case_id") or "unknown-case")
            path = target_dir / f"{_safe_filename(canonical_case_id)}__{_safe_filename(law_uid)}__expanded.json"
            _write_json(path, row)
        result["targets"][target] = {
            "detail_supported": True,
            "source_file_count": len(selected_rows),
            "expanded_count": len(selected_rows),
        }
        written_records.extend(selected_rows)

    result["expanded_count"] = len(written_records)
    result["records"] = written_records
    _write_jsonl(save_root_dir / "relation_records.jsonl", written_records)
    _write_json(
        save_root_dir / f"{_safe_filename(root_law_name)}__expanded_manifest.json",
        result,
    )

    return result
