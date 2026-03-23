from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlparse

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover - optional in offline test env
    httpx = None  # type: ignore[assignment]

from src.common.appendix_scope import is_target_appendix
from src.common.io_utils import _read_json, _safe_filename, _write_json

DEFAULT_APPENDIX_DOWNLOAD_BASE_URL = "https://www.law.go.kr"
SUPPORTED_DIRECT_DOWNLOAD_ROLES = ("pdf_download_link", "file_download_link")


def _safe_asset_filename(filename: str, *, fallback_stem: str) -> str:
    raw_name = Path(str(filename).strip()).name
    suffix = "".join(Path(raw_name).suffixes)
    stem = raw_name[: -len(suffix)] if suffix else raw_name
    safe_stem = _safe_filename(stem or fallback_stem)
    safe_suffix = suffix.lower()
    return f"{safe_stem}{safe_suffix}" if safe_suffix else safe_stem


def _normalize_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.scheme in {"http", "https", "file"})


def _infer_asset_kind(
    *,
    asset_role: str,
    declared_file_name: str | None,
    source_url: str | None,
) -> str:
    if asset_role == "pdf_download_link":
        return "pdf"

    suffix_source = declared_file_name or source_url or ""
    suffix = Path(urlparse(str(suffix_source)).path).suffix.lower()

    if suffix == ".pdf":
        return "pdf"
    if suffix in {".hwp", ".hwpx"}:
        return suffix.lstrip(".")
    if suffix in {".gif", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}:
        return "image"
    return "binary"


def _resolve_asset_url(
    source_url: str | None,
    *,
    download_base_url: str,
) -> str | None:
    if source_url is None:
        return None

    normalized = str(source_url).strip()
    if not normalized:
        return None

    if _looks_like_url(normalized):
        return normalized

    if Path(normalized).exists():
        return str(Path(normalized).resolve())

    return urljoin(download_base_url.rstrip("/") + "/", normalized)


def _resolve_file_name(
    *,
    asset_role: str,
    asset_kind: str,
    declared_file_name: str | None,
    source_url: str | None,
    appendix_key: str | None,
    appendix_title: str | None,
) -> str:
    fallback_stem = appendix_key or appendix_title or asset_role

    if declared_file_name:
        return _safe_asset_filename(declared_file_name, fallback_stem=fallback_stem)

    if source_url:
        parsed = urlparse(source_url)
        basename = unquote(Path(parsed.path).name)
        if basename:
            return _safe_asset_filename(basename, fallback_stem=fallback_stem)

    suffix = {
        "pdf": ".pdf",
        "hwp": ".hwp",
        "hwpx": ".hwpx",
        "image": ".img",
    }.get(asset_kind, ".bin")
    return _safe_asset_filename(f"{fallback_stem}{suffix}", fallback_stem=fallback_stem)


def _build_asset_candidate(
    *,
    appendix_record: dict[str, Any],
    asset_role: str,
    declared_file_name: str | None,
    source_url: str | None,
    download_base_url: str,
) -> dict[str, Any]:
    appendix_key = _normalize_text(appendix_record.get("appendix_key"))
    appendix_title = _normalize_text(appendix_record.get("appendix_title"))

    asset_kind = _infer_asset_kind(
        asset_role=asset_role,
        declared_file_name=declared_file_name,
        source_url=source_url,
    )
    resolved_url = _resolve_asset_url(
        source_url,
        download_base_url=download_base_url,
    )
    resolved_file_name = _resolve_file_name(
        asset_role=asset_role,
        asset_kind=asset_kind,
        declared_file_name=declared_file_name,
        source_url=resolved_url or source_url,
        appendix_key=appendix_key,
        appendix_title=appendix_title,
    )

    asset_id = "::".join(
        [
            str(appendix_record.get("id") or appendix_key or appendix_title or "appendix"),
            asset_role,
        ]
    )

    return {
        "asset_id": asset_id,
        "asset_role": asset_role,
        "asset_kind": asset_kind,
        "declared_file_name": declared_file_name,
        "resolved_file_name": resolved_file_name,
        "source_url": source_url,
        "resolved_url": resolved_url,
        "download_status": "declared_only" if resolved_url is None else "planned",
        "local_path": None,
        "http_status_code": None,
        "content_type": None,
        "byte_size": None,
        "sha256": None,
        "error_message": None,
    }


def build_asset_candidates_for_record(
    appendix_record: dict[str, Any],
    *,
    download_base_url: str = DEFAULT_APPENDIX_DOWNLOAD_BASE_URL,
) -> list[dict[str, Any]]:
    assets = appendix_record.get("download_assets") or {}
    if not isinstance(assets, dict):
        assets = {}

    candidates: list[dict[str, Any]] = []

    pdf_download_link = _normalize_text(assets.get("pdf_download_link"))
    file_download_link = _normalize_text(assets.get("file_download_link"))
    pdf_file_name = _normalize_text(assets.get("pdf_file_name"))
    hwp_file_name = _normalize_text(assets.get("hwp_file_name"))
    image_file_names = assets.get("image_file_names")
    if not isinstance(image_file_names, list):
        image_file_names = []

    if pdf_download_link is not None or pdf_file_name is not None:
        candidates.append(
            _build_asset_candidate(
                appendix_record=appendix_record,
                asset_role="pdf_download_link",
                declared_file_name=pdf_file_name,
                source_url=pdf_download_link,
                download_base_url=download_base_url,
            )
        )

    if file_download_link is not None or hwp_file_name is not None:
        candidates.append(
            _build_asset_candidate(
                appendix_record=appendix_record,
                asset_role="file_download_link",
                declared_file_name=hwp_file_name,
                source_url=file_download_link,
                download_base_url=download_base_url,
            )
        )

    for image_file_name in image_file_names:
        normalized_name = _normalize_text(image_file_name)
        if normalized_name is None:
            continue
        candidates.append(
            _build_asset_candidate(
                appendix_record=appendix_record,
                asset_role="image_declared",
                declared_file_name=normalized_name,
                source_url=None,
                download_base_url=download_base_url,
            )
        )

    return candidates


def _detect_content_type(path: Path) -> str:
    guessed_type, _ = mimetypes.guess_type(path.name)
    return guessed_type or "application/octet-stream"


def _download_binary(
    source: str,
    *,
    timeout_sec: int,
) -> tuple[bytes, str, int | None, str]:
    if source.startswith("file://"):
        parsed = urlparse(source)
        local_path = Path(unquote(parsed.path))
        if not local_path.exists():
            raise FileNotFoundError(local_path)
        return (
            local_path.read_bytes(),
            _detect_content_type(local_path),
            None,
            str(local_path.resolve()),
        )

    source_path = Path(source)
    if not urlparse(source).scheme and source_path.exists():
        return (
            source_path.read_bytes(),
            _detect_content_type(source_path),
            None,
            str(source_path.resolve()),
        )

    if httpx is None:
        raise RuntimeError("httpx is required to download appendix assets")

    response = httpx.get(source, timeout=timeout_sec, follow_redirects=True)
    response.raise_for_status()
    return (
        response.content,
        response.headers.get("content-type", "application/octet-stream"),
        response.status_code,
        str(response.url),
    )


def _write_downloaded_asset(
    *,
    source: str,
    output_path: Path,
    timeout_sec: int,
) -> dict[str, Any]:
    data, content_type, status_code, final_url = _download_binary(source, timeout_sec=timeout_sec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)

    return {
        "local_path": str(output_path),
        "http_status_code": status_code,
        "content_type": content_type,
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "final_url": final_url,
    }


def collect_appendix_assets_from_bundle(
    appendix_bundle: dict[str, Any],
    *,
    save_dir: str | Path,
    download_assets: bool = True,
    overwrite: bool = False,
    timeout_sec: int = 60,
    download_base_url: str = DEFAULT_APPENDIX_DOWNLOAD_BASE_URL,
) -> dict[str, Any]:
    law_name = str(appendix_bundle.get("law_name") or "unnamed")
    law_dir = Path(save_dir) / _safe_filename(law_name)

    appendix_records = appendix_bundle.get("appendix_records")
    if not isinstance(appendix_records, list):
        appendix_records = []

    result_records: list[dict[str, Any]] = []
    candidate_count = 0
    downloaded_count = 0
    planned_count = 0
    declared_only_count = 0
    error_count = 0

    for appendix_record in appendix_records:
        if not isinstance(appendix_record, dict):
            continue
        if not is_target_appendix(
            appendix_record.get("appendix_kind"),
            appendix_record.get("appendix_title"),
            appendix_record.get("appendix_key"),
        ):
            continue

        appendix_key = _normalize_text(appendix_record.get("appendix_key")) or _normalize_text(appendix_record.get("appendix_title")) or "appendix"
        appendix_dir = law_dir / _safe_filename(appendix_key)
        candidates = build_asset_candidates_for_record(
            appendix_record,
            download_base_url=download_base_url,
        )

        processed_candidates: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_count += 1
            local_path = appendix_dir / str(candidate["resolved_file_name"])
            updated = dict(candidate)

            if updated["resolved_url"] is None:
                declared_only_count += 1
                processed_candidates.append(updated)
                continue

            if not download_assets:
                planned_count += 1
                processed_candidates.append(updated)
                continue

            if local_path.exists() and not overwrite:
                updated["download_status"] = "skipped_existing"
                updated["local_path"] = str(local_path)
                updated["byte_size"] = local_path.stat().st_size
                updated["content_type"] = _detect_content_type(local_path)
                updated["sha256"] = hashlib.sha256(local_path.read_bytes()).hexdigest()
                downloaded_count += 1
                processed_candidates.append(updated)
                continue

            try:
                download_result = _write_downloaded_asset(
                    source=str(updated["resolved_url"]),
                    output_path=local_path,
                    timeout_sec=timeout_sec,
                )
            except Exception as exc:  # pragma: no cover - network failure branch
                updated["download_status"] = "download_error"
                updated["error_message"] = str(exc)
                error_count += 1
            else:
                updated["download_status"] = "downloaded"
                updated.update(download_result)
                downloaded_count += 1

            processed_candidates.append(updated)

        result_records.append(
            {
                "appendix_id": appendix_record.get("id"),
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
                "api_document_markdown": appendix_record.get("api_document_markdown"),
                "api_document_markdown_flat": appendix_record.get("api_document_markdown_flat"),
                "api_table_markdown_text": appendix_record.get("api_table_markdown_text"),
                "api_markdown_tables": appendix_record.get("api_markdown_tables") or [],
                "api_structured_tables": appendix_record.get("api_structured_tables") or [],
                "api_table_count": appendix_record.get("api_table_count") or 0,
                "has_substantive_text": appendix_record.get("has_substantive_text"),
                "processing_policy": appendix_record.get("processing_policy", {}),
                "asset_candidates": processed_candidates,
            }
        )

    raw_asset_bundle = {
        "law_name": appendix_bundle.get("law_name"),
        "law_id": appendix_bundle.get("law_id"),
        "mst": appendix_bundle.get("mst"),
        "ef_yd": appendix_bundle.get("ef_yd"),
        "appendix_count": len(result_records),
        "asset_candidate_count": candidate_count,
        "downloaded_count": downloaded_count,
        "planned_count": planned_count,
        "declared_only_count": declared_only_count,
        "download_error_count": error_count,
        "download_mode": "download" if download_assets else "plan_only",
        "download_base_url": download_base_url,
        "appendix_asset_records": result_records,
    }

    output_path = law_dir / f"{_safe_filename(law_name)}__appendix_assets.raw.json"
    _write_json(output_path, raw_asset_bundle)
    raw_asset_bundle["bundle_path"] = str(output_path)
    return raw_asset_bundle


def _iter_appendix_bundle_paths(normalized_appendix_base_dir: str | Path) -> Iterable[Path]:
    base_dir = Path(normalized_appendix_base_dir)
    return sorted(base_dir.rglob("*__parsed_appendix.json"))


def collect_appendix_asset_bundles(
    *,
    normalized_appendix_base_dir: str | Path = "data/normalized/01_current_law_appendix",
    save_dir: str | Path = "data/raw/01_current_law_appendix_assets",
    download_assets: bool = True,
    overwrite: bool = False,
    timeout_sec: int = 60,
    download_base_url: str = DEFAULT_APPENDIX_DOWNLOAD_BASE_URL,
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []

    total_appendix_count = 0
    total_candidate_count = 0
    total_downloaded_count = 0
    total_planned_count = 0
    total_declared_only_count = 0
    total_error_count = 0

    for path in _iter_appendix_bundle_paths(normalized_appendix_base_dir):
        appendix_bundle = _read_json(path)
        asset_bundle = collect_appendix_assets_from_bundle(
            appendix_bundle,
            save_dir=save_dir,
            download_assets=download_assets,
            overwrite=overwrite,
            timeout_sec=timeout_sec,
            download_base_url=download_base_url,
        )

        summaries.append(
            {
                "law_name": asset_bundle.get("law_name"),
                "appendix_count": asset_bundle.get("appendix_count"),
                "asset_candidate_count": asset_bundle.get("asset_candidate_count"),
                "downloaded_count": asset_bundle.get("downloaded_count"),
                "planned_count": asset_bundle.get("planned_count"),
                "declared_only_count": asset_bundle.get("declared_only_count"),
                "download_error_count": asset_bundle.get("download_error_count"),
                "bundle_path": asset_bundle.get("bundle_path"),
                "source_appendix_bundle_path": str(path),
            }
        )

        total_appendix_count += int(asset_bundle.get("appendix_count") or 0)
        total_candidate_count += int(asset_bundle.get("asset_candidate_count") or 0)
        total_downloaded_count += int(asset_bundle.get("downloaded_count") or 0)
        total_planned_count += int(asset_bundle.get("planned_count") or 0)
        total_declared_only_count += int(asset_bundle.get("declared_only_count") or 0)
        total_error_count += int(asset_bundle.get("download_error_count") or 0)

    summary = {
        "bundle_count": len(summaries),
        "appendix_count": total_appendix_count,
        "asset_candidate_count": total_candidate_count,
        "downloaded_count": total_downloaded_count,
        "planned_count": total_planned_count,
        "declared_only_count": total_declared_only_count,
        "download_error_count": total_error_count,
        "download_mode": "download" if download_assets else "plan_only",
        "download_base_url": download_base_url,
        "bundles": summaries,
    }

    _write_json(Path(save_dir) / "appendix_asset_collection_summary.json", summary)
    return summary
