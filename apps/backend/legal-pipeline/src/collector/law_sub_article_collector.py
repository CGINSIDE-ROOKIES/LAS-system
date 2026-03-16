from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from src.common.io_utils import _safe_filename, _write_json
from src.common.payload_utils import _ensure_success_payload
from src.core.http_client import execute_api_request
from src.core.request_builder import build_request

SubArticleMode = Literal["none", "all"]


def normalize_jo_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("jo_code is required")

    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        raise ValueError(f"Invalid jo_code: {value}")

    return digits.zfill(6)


def extract_jo_codes_from_parsed_law(parsed_law: dict[str, Any]) -> list[str]:
    articles = parsed_law.get("articles", [])
    if not isinstance(articles, list):
        return []

    results: list[str] = []
    seen: set[str] = set()

    for article in articles:
        if not isinstance(article, dict):
            continue

        jo_code = article.get("jo_code")
        if jo_code in (None, ""):
            continue

        try:
            normalized = normalize_jo_code(jo_code)
        except ValueError:
            continue

        if normalized in seen:
            continue

        seen.add(normalized)
        results.append(normalized)

    return results


def fetch_sub_article_by_ref(
    registry: dict[str, Any],
    oc: str,
    law_ref: dict[str, Any],
    jo_code: str | int,
) -> dict[str, Any]:
    normalized_jo = normalize_jo_code(jo_code)

    runtime_params: dict[str, Any] = {
        "OC": oc,
        "JO": normalized_jo,
    }

    mst = law_ref.get("mst")
    ef_yd = law_ref.get("ef_yd")
    law_id = law_ref.get("law_id")

    if mst and ef_yd:
        runtime_params["MST"] = str(mst)
        runtime_params["efYd"] = str(ef_yd)
    elif law_id:
        runtime_params["ID"] = str(law_id)
    else:
        raise ValueError("law_ref must contain either (mst + ef_yd) or law_id")

    request = build_request(
        registry,
        "law_current_article",
        runtime_params,
    )
    result = execute_api_request(request)
    payload = result["parsed"]

    if not isinstance(payload, dict):
        raise RuntimeError("law_current_article parsed payload must be dict")

    _ensure_success_payload("law_current_article", payload)
    return {
        "response_meta": {
            "format": result["format"],
            "content_type": result["content_type"],
            "status_code": result["status_code"],
            "url": result["url"],
        },
        "raw_text": result["text"],
        "parsed": payload,
    }


def collect_sub_article_by_ref(
    registry: dict[str, Any],
    oc: str,
    law_ref: dict[str, Any],
    jo_code: str | int,
    save_dir: str | Path | None = None,
) -> dict[str, Any]:
    normalized_jo = normalize_jo_code(jo_code)

    sub_article_result = fetch_sub_article_by_ref(
        registry=registry,
        oc=oc,
        law_ref=law_ref,
        jo_code=normalized_jo,
    )
    payload = sub_article_result["parsed"]

    record = {
        "law_name": law_ref.get("law_name"),
        "law_ref": law_ref,
        "jo_code": normalized_jo,
        "sub_article_payload": payload,
        "sub_article_response": sub_article_result,
    }

    if save_dir is not None:
        base_dir = Path(save_dir)
        stem_name = str(law_ref.get("law_name") or law_ref.get("law_id") or "unnamed")
        stem = _safe_filename(stem_name)

        _write_json(
            base_dir / f"{stem}__JO_{normalized_jo}__sub_article.parsed.json",
            payload,
        )
        _write_json(
            base_dir / f"{stem}__JO_{normalized_jo}__sub_article.response.json",
            sub_article_result,
        )
        _write_json(
            base_dir / f"{stem}__JO_{normalized_jo}__sub_article_bundle.json",
            record,
        )

    return record


def collect_sub_articles_for_law(
    registry: dict[str, Any],
    oc: str,
    law_ref: dict[str, Any],
    jo_codes: list[str | int],
    save_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for jo_code in jo_codes:
        record = collect_sub_article_by_ref(
            registry=registry,
            oc=oc,
            law_ref=law_ref,
            jo_code=jo_code,
            save_dir=save_dir,
        )
        results.append(record)

    return results


def collect_sub_articles_for_parsed_law(
    registry: dict[str, Any],
    oc: str,
    law_ref: dict[str, Any],
    parsed_law: dict[str, Any],
    mode: SubArticleMode = "none",
    save_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    if mode == "none":
        return []

    if mode != "all":
        raise ValueError(f"Unsupported sub article mode: {mode}")

    jo_codes = extract_jo_codes_from_parsed_law(parsed_law)
    if not jo_codes:
        return []

    return collect_sub_articles_for_law(
        registry=registry,
        oc=oc,
        law_ref=law_ref,
        jo_codes=jo_codes,
        save_dir=save_dir,
    )
