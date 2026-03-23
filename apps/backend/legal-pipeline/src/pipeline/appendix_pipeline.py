from __future__ import annotations

from pathlib import Path
from typing import Any

from src.collector.appendix_asset_collector import (
    DEFAULT_APPENDIX_DOWNLOAD_BASE_URL,
    collect_appendix_asset_bundles,
)
from src.common.io_utils import _write_json
from src.export.appendix_dataset_builder import build_and_write_appendix_datasets
from src.parser.appendix_asset_parser import normalize_appendix_asset_bundles


def run_appendix_asset_pipeline(
    *,
    normalized_appendix_base_dir: str | Path = "data/normalized/01_current_law_appendix",
    raw_asset_base_dir: str | Path = "data/raw/01_current_law_appendix_assets",
    normalized_asset_base_dir: str | Path = "data/normalized/01_current_law_appendix_assets",
    output_dir: str | Path = "data/dataset",
    manifest_path: str | Path = "data/manifest/appendix_asset_pipeline_summary.json",
    download_assets: bool = True,
    overwrite_assets: bool = False,
    timeout_sec: int = 60,
    download_base_url: str = DEFAULT_APPENDIX_DOWNLOAD_BASE_URL,
    max_chars: int = 1200,
    overlap: int = 150,
    build_dataset: bool = True,
) -> dict[str, Any]:
    collection_summary = collect_appendix_asset_bundles(
        normalized_appendix_base_dir=normalized_appendix_base_dir,
        save_dir=raw_asset_base_dir,
        download_assets=download_assets,
        overwrite=overwrite_assets,
        timeout_sec=timeout_sec,
        download_base_url=download_base_url,
    )

    parse_summary = normalize_appendix_asset_bundles(
        raw_asset_base_dir=raw_asset_base_dir,
        save_dir=normalized_asset_base_dir,
    )

    dataset_manifest: dict[str, Any] | None = None
    if build_dataset:
        dataset_manifest = build_and_write_appendix_datasets(
            normalized_appendix_base_dir=normalized_appendix_base_dir,
            normalized_appendix_asset_base_dir=normalized_asset_base_dir,
            output_dir=output_dir,
            max_chars=max_chars,
            overlap=overlap,
        )

    result = {
        "normalized_appendix_base_dir": str(normalized_appendix_base_dir),
        "raw_asset_base_dir": str(raw_asset_base_dir),
        "normalized_asset_base_dir": str(normalized_asset_base_dir),
        "download_assets": download_assets,
        "overwrite_assets": overwrite_assets,
        "download_base_url": download_base_url,
        "collection_summary": collection_summary,
        "parse_summary": parse_summary,
        "dataset_manifest": dataset_manifest,
    }

    _write_json(Path(manifest_path), result)
    return result
