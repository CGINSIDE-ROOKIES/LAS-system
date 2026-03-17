from pathlib import Path

from reportlab.pdfgen import canvas

from src.collector.appendix_asset_collector import collect_appendix_asset_bundles
from src.common.io_utils import _read_json, _write_json
from src.parser.appendix_asset_parser import normalize_appendix_asset_bundles


def _make_pdf(path: Path, lines: list[str]) -> None:
    pdf = canvas.Canvas(str(path))
    y = 800
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 18
    pdf.save()


def test_collect_appendix_asset_bundles_downloads_local_assets_and_writes_manifest(tmp_path):
    normalized_appendix_dir = tmp_path / "normalized" / "01_current_law_appendix" / "근로기준법"
    bundle_path = normalized_appendix_dir / "근로기준법__parsed_appendix.json"

    source_dir = tmp_path / "source_assets"
    source_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = source_dir / "sample_table.pdf"
    hwp_path = source_dir / "sample_form.hwp"
    _make_pdf(pdf_path, ["Disease Table", "A B"])
    hwp_path.write_bytes(b"fake-hwp-binary")

    _write_json(
        bundle_path,
        {
            "law_name": "근로기준법",
            "law_id": "001",
            "appendix_records": [
                {
                    "id": "appendix::근로기준법::000200E",
                    "law_name": "근로기준법",
                    "law_id": "001",
                    "appendix_key": "000200E",
                    "appendix_no": "0002",
                    "appendix_type": "table_appendix",
                    "appendix_title": "질환 분류표",
                    "api_text_raw": "A B",
                    "api_text": "A B",
                    "has_substantive_text": True,
                    "processing_policy": {},
                    "download_assets": {
                        "pdf_download_link": str(pdf_path.resolve()),
                        "pdf_file_name": "sample_table.pdf",
                        "file_download_link": str(hwp_path.resolve()),
                        "hwp_file_name": "sample_form.hwp",
                        "image_file_names": ["sample_table.gif"],
                    },
                }
            ],
        },
    )

    summary = collect_appendix_asset_bundles(
        normalized_appendix_base_dir=tmp_path / "normalized" / "01_current_law_appendix",
        save_dir=tmp_path / "raw" / "01_current_law_appendix_assets",
        download_assets=True,
    )

    assert summary["bundle_count"] == 1
    assert summary["asset_candidate_count"] == 3
    assert summary["downloaded_count"] == 2
    assert summary["declared_only_count"] == 1

    raw_bundle = _read_json(Path(summary["bundles"][0]["bundle_path"]))
    record = raw_bundle["appendix_asset_records"][0]
    statuses = {asset["asset_role"]: asset["download_status"] for asset in record["asset_candidates"]}

    assert statuses["pdf_download_link"] == "downloaded"
    assert statuses["file_download_link"] == "downloaded"
    assert statuses["image_declared"] == "declared_only"

    local_paths = [
        Path(asset["local_path"])
        for asset in record["asset_candidates"]
        if asset["local_path"] is not None
    ]
    assert all(path.exists() for path in local_paths)


def test_normalize_appendix_asset_bundles_extracts_pdf_text_and_selects_pdf_for_tables(tmp_path):
    normalized_appendix_dir = tmp_path / "normalized" / "01_current_law_appendix" / "근로기준법"
    bundle_path = normalized_appendix_dir / "근로기준법__parsed_appendix.json"

    source_dir = tmp_path / "source_assets"
    source_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = source_dir / "sample_table.pdf"
    _make_pdf(pdf_path, ["Disease Table", "Disease Code", "Cold J00"])

    _write_json(
        bundle_path,
        {
            "law_name": "근로기준법",
            "law_id": "001",
            "appendix_records": [
                {
                    "id": "appendix::근로기준법::000200E",
                    "law_name": "근로기준법",
                    "law_id": "001",
                    "appendix_key": "000200E",
                    "appendix_no": "0002",
                    "appendix_type": "table_appendix",
                    "appendix_title": "질환 분류표",
                    "api_text_raw": "┌─┬─┐\n│A│B│\n└─┴─┘",
                    "api_text": "┌─┬─┐ │A│B│ └─┴─┘",
                    "has_substantive_text": True,
                    "processing_policy": {},
                    "download_assets": {
                        "pdf_download_link": str(pdf_path.resolve()),
                        "pdf_file_name": "sample_table.pdf",
                        "file_download_link": None,
                        "hwp_file_name": None,
                        "image_file_names": [],
                    },
                }
            ],
        },
    )

    collect_appendix_asset_bundles(
        normalized_appendix_base_dir=tmp_path / "normalized" / "01_current_law_appendix",
        save_dir=tmp_path / "raw" / "01_current_law_appendix_assets",
        download_assets=True,
    )
    summary = normalize_appendix_asset_bundles(
        raw_asset_base_dir=tmp_path / "raw" / "01_current_law_appendix_assets",
        save_dir=tmp_path / "normalized" / "01_current_law_appendix_assets",
    )

    assert summary["bundle_count"] == 1
    assert summary["successful_extraction_count"] == 1

    parsed_bundle = _read_json(
        tmp_path
        / "normalized"
        / "01_current_law_appendix_assets"
        / "근로기준법"
        / "근로기준법__appendix_assets.parsed.json"
    )
    record = parsed_bundle["appendix_asset_records"][0]

    assert record["best_text_source"] == "pdf_text"
    assert "Disease Table" in (record["best_text_raw"] or "")
    assert record["successful_extraction_count"] == 1
    assert record["assets"][0]["extraction_status"] == "success"
