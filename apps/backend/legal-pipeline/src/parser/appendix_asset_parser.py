from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

try:
    from pypdf import PdfReader
except ModuleNotFoundError:  # pragma: no cover - optional in offline test env
    PdfReader = None  # type: ignore[assignment]

try:
    import pdfplumber
except ModuleNotFoundError:  # pragma: no cover - optional in offline test env
    pdfplumber = None  # type: ignore[assignment]

from src.common.io_utils import _read_json, _safe_filename, _write_json
from src.parser.appendix_parser import _count_table_signals
from src.parser.law_parser import _looks_table_like, _normalize_text_flat, _normalize_text_preserve_structure


SUPPORTED_EXTRACTION_KINDS = {"pdf"}


def _score_text_quality(raw_text: str | None) -> int:
    if raw_text in (None, ""):
        return 0
    text = str(raw_text)
    line_count = len([line for line in text.splitlines() if line.strip()])
    char_count = len(text)
    table_signal_count = _count_table_signals(text)
    return char_count + (line_count * 2) + (table_signal_count * 4)


def _extract_pdf_with_pypdf(path: Path) -> dict[str, Any]:
    if PdfReader is None:
        return {
            "engine": "pypdf",
            "status": "engine_unavailable",
            "page_count": 0,
            "raw_text": None,
        }

    reader = PdfReader(str(path))
    page_texts: list[str] = []

    for page in reader.pages:
        page_texts.append((page.extract_text() or "").strip())

    raw_text = "\n\n".join(text for text in page_texts if text)
    return {
        "engine": "pypdf",
        "status": "success" if raw_text else "empty_text",
        "page_count": len(reader.pages),
        "raw_text": raw_text or None,
    }


def _extract_pdf_with_pdfplumber(path: Path) -> dict[str, Any]:
    if pdfplumber is None:
        return {
            "engine": "pdfplumber",
            "status": "engine_unavailable",
            "page_count": 0,
            "raw_text": None,
        }

    with pdfplumber.open(path) as pdf:
        page_texts = [(page.extract_text() or "").strip() for page in pdf.pages]

    raw_text = "\n\n".join(text for text in page_texts if text)
    return {
        "engine": "pdfplumber",
        "status": "success" if raw_text else "empty_text",
        "page_count": len(page_texts),
        "raw_text": raw_text or None,
    }


def extract_text_from_pdf(path: str | Path) -> dict[str, Any]:
    pdf_path = Path(path)
    candidates: list[dict[str, Any]] = []

    for extractor in (_extract_pdf_with_pypdf, _extract_pdf_with_pdfplumber):
        try:
            result = extractor(pdf_path)
        except Exception as exc:  # pragma: no cover - extractor failure branch
            candidates.append(
                {
                    "engine": extractor.__name__,
                    "status": "extract_error",
                    "page_count": 0,
                    "raw_text": None,
                    "error_message": str(exc),
                }
            )
            continue

        result["quality_score"] = _score_text_quality(result.get("raw_text"))
        candidates.append(result)

    best = max(candidates, key=lambda item: int(item.get("quality_score") or 0), default=None)
    if not best:
        return {
            "extraction_status": "extract_error",
            "extraction_engine": None,
            "page_count": 0,
            "text_raw": None,
            "text": None,
            "char_count": 0,
            "line_count": 0,
            "table_signal_count": 0,
            "has_table_markup": False,
            "error_message": "No PDF extractor available",
        }

    raw_text = _normalize_text_preserve_structure(best.get("raw_text"))
    text = _normalize_text_flat(best.get("raw_text"))
    line_count = len([line for line in (raw_text or "").splitlines() if line.strip()])

    return {
        "extraction_status": "success" if raw_text else str(best.get("status") or "empty_text"),
        "extraction_engine": best.get("engine"),
        "page_count": int(best.get("page_count") or 0),
        "text_raw": raw_text,
        "text": text,
        "char_count": len(raw_text or text or ""),
        "line_count": line_count,
        "table_signal_count": _count_table_signals(raw_text),
        "has_table_markup": _looks_table_like(raw_text),
        "error_message": best.get("error_message"),
    }


def _choose_best_text(
    *,
    appendix_type: str,
    api_text_raw: str | None,
    api_text: str | None,
    extracted_assets: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_api_raw = _normalize_text_preserve_structure(api_text_raw or api_text)
    normalized_api = _normalize_text_flat(api_text or api_text_raw)
    api_char_count = len(normalized_api_raw or normalized_api or "")

    successful_pdf_assets = [
        asset
        for asset in extracted_assets
        if asset.get("asset_kind") == "pdf"
        and asset.get("extraction_status") == "success"
        and asset.get("text_raw") not in (None, "")
    ]
    best_pdf_asset = max(
        successful_pdf_assets,
        key=lambda item: int(item.get("char_count") or 0),
        default=None,
    )

    if appendix_type in {"table_appendix", "form_appendix"}:
        if best_pdf_asset is not None:
            return {
                "best_text_source": "pdf_text",
                "best_text_reason": "table_or_form_prefers_pdf_when_available",
                "best_text_raw": best_pdf_asset.get("text_raw"),
                "best_text": best_pdf_asset.get("text"),
                "best_asset_id": best_pdf_asset.get("asset_id"),
                "best_asset_local_path": best_pdf_asset.get("local_path"),
            }
        if normalized_api_raw or normalized_api:
            return {
                "best_text_source": "api_text",
                "best_text_reason": "fallback_to_api_text",
                "best_text_raw": normalized_api_raw,
                "best_text": normalized_api,
                "best_asset_id": None,
                "best_asset_local_path": None,
            }
        return {
            "best_text_source": "none",
            "best_text_reason": "no_text_available",
            "best_text_raw": None,
            "best_text": None,
            "best_asset_id": None,
            "best_asset_local_path": None,
        }

    if appendix_type == "appendix_document":
        if best_pdf_asset is not None and not normalized_api_raw:
            return {
                "best_text_source": "pdf_text",
                "best_text_reason": "api_text_missing_pdf_available",
                "best_text_raw": best_pdf_asset.get("text_raw"),
                "best_text": best_pdf_asset.get("text"),
                "best_asset_id": best_pdf_asset.get("asset_id"),
                "best_asset_local_path": best_pdf_asset.get("local_path"),
            }
        if best_pdf_asset is not None and int(best_pdf_asset.get("char_count") or 0) >= max(api_char_count + 120, int(api_char_count * 1.25)):
            return {
                "best_text_source": "pdf_text",
                "best_text_reason": "pdf_text_substantially_richer_than_api_text",
                "best_text_raw": best_pdf_asset.get("text_raw"),
                "best_text": best_pdf_asset.get("text"),
                "best_asset_id": best_pdf_asset.get("asset_id"),
                "best_asset_local_path": best_pdf_asset.get("local_path"),
            }
        if normalized_api_raw or normalized_api:
            return {
                "best_text_source": "api_text",
                "best_text_reason": "api_text_kept_as_primary",
                "best_text_raw": normalized_api_raw,
                "best_text": normalized_api,
                "best_asset_id": None,
                "best_asset_local_path": None,
            }
        if best_pdf_asset is not None:
            return {
                "best_text_source": "pdf_text",
                "best_text_reason": "fallback_to_pdf_text",
                "best_text_raw": best_pdf_asset.get("text_raw"),
                "best_text": best_pdf_asset.get("text"),
                "best_asset_id": best_pdf_asset.get("asset_id"),
                "best_asset_local_path": best_pdf_asset.get("local_path"),
            }

    if normalized_api_raw or normalized_api:
        return {
            "best_text_source": "api_text",
            "best_text_reason": "metadata_or_api_fallback",
            "best_text_raw": normalized_api_raw,
            "best_text": normalized_api,
            "best_asset_id": None,
            "best_asset_local_path": None,
        }

    if best_pdf_asset is not None:
        return {
            "best_text_source": "pdf_text",
            "best_text_reason": "metadata_fallback_to_pdf_text",
            "best_text_raw": best_pdf_asset.get("text_raw"),
            "best_text": best_pdf_asset.get("text"),
            "best_asset_id": best_pdf_asset.get("asset_id"),
            "best_asset_local_path": best_pdf_asset.get("local_path"),
        }

    return {
        "best_text_source": "none",
        "best_text_reason": "no_text_available",
        "best_text_raw": None,
        "best_text": None,
        "best_asset_id": None,
        "best_asset_local_path": None,
    }


def parse_appendix_asset_bundle(raw_asset_bundle: dict[str, Any]) -> dict[str, Any]:
    appendix_asset_records = raw_asset_bundle.get("appendix_asset_records")
    if not isinstance(appendix_asset_records, list):
        appendix_asset_records = []

    parsed_records: list[dict[str, Any]] = []
    extracted_asset_count = 0
    successful_extraction_count = 0

    for appendix_record in appendix_asset_records:
        if not isinstance(appendix_record, dict):
            continue

        asset_candidates = appendix_record.get("asset_candidates")
        if not isinstance(asset_candidates, list):
            asset_candidates = []

        parsed_assets: list[dict[str, Any]] = []
        for asset in asset_candidates:
            if not isinstance(asset, dict):
                continue

            parsed_asset = {
                "asset_id": asset.get("asset_id"),
                "asset_role": asset.get("asset_role"),
                "asset_kind": asset.get("asset_kind"),
                "declared_file_name": asset.get("declared_file_name"),
                "resolved_file_name": asset.get("resolved_file_name"),
                "local_path": asset.get("local_path"),
                "download_status": asset.get("download_status"),
                "content_type": asset.get("content_type"),
                "byte_size": asset.get("byte_size"),
                "sha256": asset.get("sha256"),
                "source_url": asset.get("source_url"),
                "resolved_url": asset.get("resolved_url"),
            }

            local_path_value = asset.get("local_path")
            if asset.get("download_status") not in {"downloaded", "skipped_existing"} or local_path_value in (None, ""):
                parsed_asset.update(
                    {
                        "extraction_status": "not_downloaded",
                        "extraction_engine": None,
                        "page_count": 0,
                        "text_raw": None,
                        "text": None,
                        "char_count": 0,
                        "line_count": 0,
                        "table_signal_count": 0,
                        "has_table_markup": False,
                        "error_message": asset.get("error_message"),
                    }
                )
                parsed_assets.append(parsed_asset)
                continue

            extracted_asset_count += 1
            asset_kind = str(asset.get("asset_kind") or "binary")
            if asset_kind not in SUPPORTED_EXTRACTION_KINDS:
                parsed_asset.update(
                    {
                        "extraction_status": "unsupported_kind",
                        "extraction_engine": None,
                        "page_count": 0,
                        "text_raw": None,
                        "text": None,
                        "char_count": 0,
                        "line_count": 0,
                        "table_signal_count": 0,
                        "has_table_markup": False,
                        "error_message": None,
                    }
                )
                parsed_assets.append(parsed_asset)
                continue

            extraction_result = extract_text_from_pdf(str(local_path_value))
            if extraction_result.get("extraction_status") == "success":
                successful_extraction_count += 1
            parsed_asset.update(extraction_result)
            parsed_assets.append(parsed_asset)

        best_text = _choose_best_text(
            appendix_type=str(appendix_record.get("appendix_type") or "appendix_document"),
            api_text_raw=appendix_record.get("api_text_raw"),
            api_text=appendix_record.get("api_text"),
            extracted_assets=parsed_assets,
        )

        parsed_records.append(
            {
                "appendix_id": appendix_record.get("appendix_id"),
                "appendix_key": appendix_record.get("appendix_key"),
                "appendix_no": appendix_record.get("appendix_no"),
                "appendix_type": appendix_record.get("appendix_type"),
                "appendix_title": appendix_record.get("appendix_title"),
                "law_name": appendix_record.get("law_name"),
                "law_id": appendix_record.get("law_id"),
                "mst": appendix_record.get("mst"),
                "ef_yd": appendix_record.get("ef_yd"),
                "kind_name": appendix_record.get("kind_name"),
                "api_text_raw": appendix_record.get("api_text_raw"),
                "api_text": appendix_record.get("api_text"),
                "has_substantive_text": appendix_record.get("has_substantive_text"),
                "processing_policy": appendix_record.get("processing_policy", {}),
                "downloaded_asset_count": sum(
                    1
                    for asset in parsed_assets
                    if asset.get("download_status") in {"downloaded", "skipped_existing"}
                ),
                "extractable_asset_count": sum(
                    1 for asset in parsed_assets if asset.get("asset_kind") in SUPPORTED_EXTRACTION_KINDS
                ),
                "successful_extraction_count": sum(
                    1 for asset in parsed_assets if asset.get("extraction_status") == "success"
                ),
                **best_text,
                "assets": parsed_assets,
            }
        )

    return {
        "law_name": raw_asset_bundle.get("law_name"),
        "law_id": raw_asset_bundle.get("law_id"),
        "mst": raw_asset_bundle.get("mst"),
        "ef_yd": raw_asset_bundle.get("ef_yd"),
        "appendix_count": len(parsed_records),
        "parsed_asset_bundle_count": len(parsed_records),
        "downloaded_asset_count": sum(
            int(record.get("downloaded_asset_count") or 0) for record in parsed_records
        ),
        "extractable_asset_count": sum(
            int(record.get("extractable_asset_count") or 0) for record in parsed_records
        ),
        "successful_extraction_count": sum(
            int(record.get("successful_extraction_count") or 0) for record in parsed_records
        ),
        "raw_asset_candidate_count": raw_asset_bundle.get("asset_candidate_count"),
        "raw_downloaded_count": raw_asset_bundle.get("downloaded_count"),
        "asset_extractions_attempted": extracted_asset_count,
        "asset_extractions_successful": successful_extraction_count,
        "appendix_asset_records": parsed_records,
    }


def save_parsed_appendix_asset_bundle(
    parsed_asset_bundle: dict[str, Any],
    *,
    save_dir: str | Path,
) -> Path:
    law_name = str(parsed_asset_bundle.get("law_name") or "unnamed")
    output_path = Path(save_dir) / _safe_filename(law_name) / f"{_safe_filename(law_name)}__appendix_assets.parsed.json"
    _write_json(output_path, parsed_asset_bundle)
    return output_path


def _iter_raw_asset_bundle_paths(raw_asset_base_dir: str | Path) -> Iterable[Path]:
    return sorted(Path(raw_asset_base_dir).rglob("*__appendix_assets.raw.json"))


def normalize_appendix_asset_bundles(
    *,
    raw_asset_base_dir: str | Path = "data/raw/01_current_law_appendix_assets",
    save_dir: str | Path = "data/normalized/01_current_law_appendix_assets",
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []

    bundle_count = 0
    appendix_count = 0
    downloaded_asset_count = 0
    successful_extraction_count = 0

    for path in _iter_raw_asset_bundle_paths(raw_asset_base_dir):
        raw_asset_bundle = _read_json(path)
        parsed_asset_bundle = parse_appendix_asset_bundle(raw_asset_bundle)
        saved_path = save_parsed_appendix_asset_bundle(
            parsed_asset_bundle,
            save_dir=save_dir,
        )

        summaries.append(
            {
                "law_name": parsed_asset_bundle.get("law_name"),
                "appendix_count": parsed_asset_bundle.get("appendix_count"),
                "downloaded_asset_count": parsed_asset_bundle.get("downloaded_asset_count"),
                "successful_extraction_count": parsed_asset_bundle.get("successful_extraction_count"),
                "bundle_path": str(saved_path),
                "source_raw_asset_bundle_path": str(path),
            }
        )

        bundle_count += 1
        appendix_count += int(parsed_asset_bundle.get("appendix_count") or 0)
        downloaded_asset_count += int(parsed_asset_bundle.get("downloaded_asset_count") or 0)
        successful_extraction_count += int(parsed_asset_bundle.get("successful_extraction_count") or 0)

    summary = {
        "bundle_count": bundle_count,
        "appendix_count": appendix_count,
        "downloaded_asset_count": downloaded_asset_count,
        "successful_extraction_count": successful_extraction_count,
        "bundles": summaries,
    }

    _write_json(Path(save_dir) / "appendix_asset_parse_summary.json", summary)
    return summary
