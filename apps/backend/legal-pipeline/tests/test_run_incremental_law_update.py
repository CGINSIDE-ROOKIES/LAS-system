import json

from scripts.run_incremental_law_update import (
    _build_filtered_appendix_asset_base_dir,
    _build_empty_patch_manifest,
    _build_opensearch_incremental_command,
    _build_qdrant_incremental_commands,
)
from src.common.io_utils import _write_json


def test_build_filtered_appendix_asset_base_dir_excludes_changed_families(tmp_path):
    asset_base_dir = tmp_path / "normalized" / "01_current_law_appendix_assets"
    keep_path = asset_base_dir / "근로기준법" / "근로기준법__appendix_assets.parsed.json"
    drop_path = asset_base_dir / "산업안전보건법" / "산업안전보건법__appendix_assets.parsed.json"

    _write_json(keep_path, {"appendix_asset_records": [{"appendix_id": "A-1"}]})
    _write_json(drop_path, {"appendix_asset_records": [{"appendix_id": "B-1"}]})

    filtered_base_dir, temp_dir = _build_filtered_appendix_asset_base_dir(
        asset_base_dir,
        excluded_root_law_names=["산업안전보건법"],
    )

    try:
        assert filtered_base_dir is not None
        kept_files = sorted(
            path.relative_to(filtered_base_dir).as_posix()
            for path in filtered_base_dir.rglob("*__appendix_assets.parsed.json")
        )
        assert kept_files == ["근로기준법/근로기준법__appendix_assets.parsed.json"]
        kept_payload = json.loads((filtered_base_dir / kept_files[0]).read_text(encoding="utf-8"))
        assert kept_payload["appendix_asset_records"][0]["appendix_id"] == "A-1"
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def test_build_qdrant_incremental_commands_includes_embed_and_optional_dry_run(tmp_path):
    commands = _build_qdrant_incremental_commands(
        reg_dt="20260325",
        base_dir=tmp_path,
        patch_dir=tmp_path / "dataset" / "patches" / "20260325",
        skip_embed=False,
        upload_dry_run=True,
    )

    assert commands[0][1] == "scripts/embed_qdrant_incremental.py"
    assert commands[0][-1] == "20260325"
    assert commands[1][1] == "scripts/upload/load_qdrant_incremental.py"
    assert commands[1][-1] == "--dry-run"


def test_build_opensearch_incremental_command_respects_skip_and_dry_run(tmp_path):
    assert (
        _build_opensearch_incremental_command(
            reg_dt="20260325",
            base_dir=tmp_path,
            patch_dir=tmp_path / "dataset" / "patches" / "20260325",
            skip_opensearch_upload=True,
            opensearch_dry_run=False,
        )
        is None
    )

    command = _build_opensearch_incremental_command(
        reg_dt="20260325",
        base_dir=tmp_path,
        patch_dir=tmp_path / "dataset" / "patches" / "20260325",
        skip_opensearch_upload=False,
        opensearch_dry_run=True,
    )

    assert command is not None
    assert command[1] == "scripts/upload/load_opensearch_incremental.py"
    assert command[-1] == "--dry-run"


def test_build_empty_patch_manifest_writes_zero_count_artifacts(tmp_path):
    patch_dir = tmp_path / "dataset" / "patches" / "20260330"

    manifest = _build_empty_patch_manifest(
        patch_dir=patch_dir,
        delta_batch_id="20260330",
    )

    assert manifest["delta_batch_id"] == "20260330"
    assert manifest["legal_corpus_upsert_count"] == 0
    assert manifest["legal_relations_delete_count"] == 0
    assert json.loads((patch_dir / "delta_manifest.json").read_text(encoding="utf-8"))["delta_batch_id"] == "20260330"
    assert (patch_dir / "legal_corpus.upsert.jsonl").read_text(encoding="utf-8") == ""
    assert (patch_dir / "legal_relations.delete.jsonl").read_text(encoding="utf-8") == ""
