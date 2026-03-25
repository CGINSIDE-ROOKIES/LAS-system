import json

from scripts.run_incremental_law_update import _build_filtered_appendix_asset_base_dir
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
