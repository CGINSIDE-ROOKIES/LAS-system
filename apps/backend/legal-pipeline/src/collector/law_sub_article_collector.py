from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from src.common.io_utils import _safe_filename, _write_json
from src.common.payload_utils import _ensure_success_payload
from src.core.http_client import execute_json_request
from src.core.request_builder import build_request

SubArticleMode = Literal["none", "first", "all"]


def _safe_filename(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^\w가-힣.-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "unnamed"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_generic_error_payload(payload: dict[str, Any]) -> bool:
    keys = set(payload.keys())
    return keys.issubset({"result", "msg"}) and "msg" in payload


def _ensure_success_payload(endpoint_key: str, payload: dict[str, Any]) -> None:
    if _is_generic_error_payload(payload):
        raise RuntimeError(
            f"{endpoint_key} returned error payload: {payload}"
        )


def normalize_jo_code(jo_code: Any) -> str:
    if jo_code in (None, ""):
        raise ValueError("jo_code is required")

    text = str(jo_code).strip()
    if re.fullmatch(r"\d{6}", text):
        return text

    digits = re.sub(r"\D", "", text)
    if not digits:
        raise ValueError(f"Invalid jo_code: {jo_code}")

    if len(digits) > 6:
        digits = digits[-6:]

    return digits.zfill(6)


def get_article_jo_codes(parsed_law: dict[str, Any]) -> list[str]:
    articles = parsed_law.get("articles", [])
    if not isinstance(articles, list):
        raise ValueError("parsed_law.articles must be a list")

    codes: list[str] = []
    seen: set[str] = set()

    for article in articles:
        if not isinstance(article, dict):
            continue

        jo_code = article.get("jo_code")
        if jo_code in (None, ""):
            continue

        normalized = normalize_jo_code(jo_code)
        if normalized in seen:
            continue

        seen.add(normalized)
        codes.append(normalized)

    return codes


def fetch_sub_article_by_ref(
    registry: dict[str, Any],
    oc: str,
    law_ref: dict[str, Any],
    jo_code: str,
    hang_code: str | None = None,
    ho_code: str | None = None,
    mok_code: str | None = None,
) -> dict[str, Any]:
    runtime_params: dict[str, Any] = {
        "OC": oc,
        "JO": normalize_jo_code(jo_code),
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

    if hang_code:
        runtime_params["HANG"] = normalize_jo_code(hang_code)
    if ho_code:
        runtime_params["HO"] = normalize_jo_code(ho_code)
    if mok_code:
        runtime_params["MOK"] = str(mok_code)

    request = build_request(
        registry,
        "law_current_article",
        runtime_params,
    )
    payload = execute_json_request(request)
    _ensure_success_payload("law_current_article", payload)
    return payload


def collect_sub_article_by_ref(
    registry: dict[str, Any],
    oc: str,
    law_ref: dict[str, Any],
    jo_code: str,
    save_dir: str | Path | None = None,
) -> dict[str, Any]:
    normalized_jo = normalize_jo_code(jo_code)

    payload = fetch_sub_article_by_ref(
        registry=registry,
        oc=oc,
        law_ref=law_ref,
        jo_code=normalized_jo,
    )

    record = {
        "law_ref": law_ref,
        "jo_code": normalized_jo,
        "sub_article_payload": payload,
    }

    if save_dir is not None:
        base_dir = Path(save_dir)
        stem = _safe_filename(str(law_ref.get("law_name") or "unnamed"))
        _write_json(
            base_dir / f"{stem}__JO_{normalized_jo}__sub_article.json",
            payload,
        )
        _write_json(
            base_dir / f"{stem}__JO_{normalized_jo}__sub_article_bundle.json",
            record,
        )

    return record


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

    jo_codes = get_article_jo_codes(parsed_law)
    if not jo_codes:
        return []

    selected_codes = jo_codes[:1] if mode == "first" else jo_codes

    results: list[dict[str, Any]] = []
    for jo_code in selected_codes:
        record = collect_sub_article_by_ref(
            registry=registry,
            oc=oc,
            law_ref=law_ref,
            jo_code=jo_code,
            save_dir=save_dir,
        )
        results.append(record)

    return results