from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    from .config import (
        BATCH_SIZE,
        COLLECTION_FLOAT_INDEX_FIELDS,
        COLLECTION_INTEGER_INDEX_FIELDS,
        COLLECTION_KEYWORD_INDEX_FIELDS,
        COLLECTION_OPENSEARCH_INDEX_NAMES,
        DROP_FIELDS_ON_EXTRACT,
        OPENSEARCH_API_KEY,
        OPENSEARCH_ENABLE_NORI_POS_FILTER,
        OPENSEARCH_PASSWORD,
        OPENSEARCH_TIMEOUT_SEC,
        OPENSEARCH_URL,
        OPENSEARCH_USERNAME,
    )
except ImportError:
    from config import (
        BATCH_SIZE,
        COLLECTION_FLOAT_INDEX_FIELDS,
        COLLECTION_INTEGER_INDEX_FIELDS,
        COLLECTION_KEYWORD_INDEX_FIELDS,
        COLLECTION_OPENSEARCH_INDEX_NAMES,
        DROP_FIELDS_ON_EXTRACT,
        OPENSEARCH_API_KEY,
        OPENSEARCH_ENABLE_NORI_POS_FILTER,
        OPENSEARCH_PASSWORD,
        OPENSEARCH_TIMEOUT_SEC,
        OPENSEARCH_URL,
        OPENSEARCH_USERNAME,
    )


ANALYZER_NAME = "kr_legal_nori"
TEXT_FIELDS = {"text", "search_text"}
NON_INDEXED_TEXT_FIELDS = {"display_text"}
EXTRA_KEYWORD_FIELDS = {
    "case_type",
    "case_type_label",
    "ef_yd",
    "mst",
    "point_id",
}
TITLE_FIELD = "title"


def opensearch_auth_headers() -> dict[str, str]:
    if OPENSEARCH_API_KEY:
        return {"Authorization": f"ApiKey {OPENSEARCH_API_KEY}"}
    if OPENSEARCH_USERNAME and OPENSEARCH_PASSWORD:
        token = base64.b64encode(f"{OPENSEARCH_USERNAME}:{OPENSEARCH_PASSWORD}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}
    return {}


def collection_index_name(collection_name: str) -> str:
    index_name = str(COLLECTION_OPENSEARCH_INDEX_NAMES.get(collection_name) or "").strip()
    if not index_name:
        raise ValueError(f"OpenSearch index name is not configured for collection: {collection_name}")
    return index_name


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row must be an object: {path}:{line_no}")
            yield row


def batched[T](items: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def opensearch_doc_id(point_id: str, max_bytes: int = 512) -> str:
    raw = point_id.encode("utf-8")
    if len(raw) <= max_bytes:
        return point_id
    import hashlib

    return f"sha1::{hashlib.sha1(raw).hexdigest()}"


def _normalize_integer_fields(row: dict[str, Any], integer_fields: Iterable[str]) -> dict[str, Any]:
    for field in integer_fields:
        value = row.get(field)
        if value is None:
            continue
        try:
            row[field] = int(value)
        except (TypeError, ValueError):
            row[field] = None
    return row


def _normalize_float_fields(row: dict[str, Any], float_fields: Iterable[str]) -> dict[str, Any]:
    for field in float_fields:
        value = row.get(field)
        if value is None:
            continue
        try:
            row[field] = float(value)
        except (TypeError, ValueError):
            row[field] = None
    return row


def build_opensearch_source(row: dict[str, Any], *, collection_name: str) -> dict[str, Any]:
    source = dict(row)
    point_id = str(source.pop("_point_id", "") or source.get("point_id") or "").strip()
    if not point_id:
        raise ValueError(f"point id is required for OpenSearch source: collection={collection_name} row_id={source.get('id')}")

    source["point_id"] = point_id
    source["collection_name"] = collection_name
    source.pop("_score", None)
    source.pop("_vector", None)
    source.pop("_vectors", None)
    for field in DROP_FIELDS_ON_EXTRACT:
        source.pop(field, None)

    integer_fields = set(COLLECTION_INTEGER_INDEX_FIELDS.get(collection_name, []))
    float_fields = set(COLLECTION_FLOAT_INDEX_FIELDS.get(collection_name, []))
    _normalize_integer_fields(source, integer_fields)
    _normalize_float_fields(source, float_fields)

    if not str(source.get("text") or "").strip():
        source["text"] = str(source.get("search_text") or source.get("display_text") or "").strip()
    if not str(source.get("search_text") or "").strip():
        source["search_text"] = str(source.get("text") or "").strip()
    if not str(source.get("display_text") or "").strip():
        source["display_text"] = str(source.get("text") or "").strip()

    return source


def _all_keyword_fields(collection_name: str) -> list[str]:
    fields = set(COLLECTION_KEYWORD_INDEX_FIELDS.get(collection_name, []))
    fields.update(EXTRA_KEYWORD_FIELDS)
    return sorted(fields)


def _all_integer_fields(collection_name: str) -> list[str]:
    return sorted(set(COLLECTION_INTEGER_INDEX_FIELDS.get(collection_name, [])))


def _all_float_fields(collection_name: str) -> list[str]:
    return sorted(set(COLLECTION_FLOAT_INDEX_FIELDS.get(collection_name, [])))


def build_index_payload(
    collection_name: str,
    *,
    number_of_shards: int = 1,
    number_of_replicas: int = 0,
    enable_nori_pos_filter: bool = OPENSEARCH_ENABLE_NORI_POS_FILTER,
    tokenizer_name: str = "nori_tokenizer",
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        TITLE_FIELD: {
            "type": "text",
            "analyzer": ANALYZER_NAME,
            "search_analyzer": ANALYZER_NAME,
            "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
        },
        "text": {"type": "text", "analyzer": ANALYZER_NAME, "search_analyzer": ANALYZER_NAME},
        "search_text": {"type": "text", "analyzer": ANALYZER_NAME, "search_analyzer": ANALYZER_NAME},
        "display_text": {"type": "text", "index": False},
    }

    for field in _all_keyword_fields(collection_name):
        if field in properties:
            continue
        properties[field] = {"type": "keyword"}

    for field in _all_integer_fields(collection_name):
        if field in properties:
            continue
        properties[field] = {"type": "integer"}

    for field in _all_float_fields(collection_name):
        if field in properties:
            continue
        properties[field] = {"type": "float"}

    analyzer_filters = ["lowercase"]
    analysis: dict[str, Any] = {
        "analyzer": {
            ANALYZER_NAME: {
                "type": "custom",
                "tokenizer": tokenizer_name,
                "filter": analyzer_filters,
            }
        }
    }

    if enable_nori_pos_filter:
        analyzer_filters.append("kr_legal_nori_posfilter")
        analysis["filter"] = {
            "kr_legal_nori_posfilter": {
                "type": "nori_part_of_speech",
                "stoptags": [
                    "E",
                    "IC",
                    "J",
                    "MAG",
                    "MAJ",
                    "MM",
                    "SP",
                    "SSC",
                    "SSO",
                    "SC",
                    "SE",
                    "XPN",
                    "XSA",
                    "XSN",
                    "XSV",
                    "UNA",
                    "NA",
                    "VSV",
                ],
            }
        }

    return {
        "settings": {
            "number_of_shards": number_of_shards,
            "number_of_replicas": number_of_replicas,
            "analysis": analysis,
        },
        "mappings": {
            "dynamic": True,
            "properties": properties,
        },
    }


def build_upsert_ndjson(
    rows: Iterable[dict[str, Any]],
    *,
    collection_name: str,
    index_name: str,
) -> tuple[str, int]:
    lines: list[str] = []
    count = 0
    for row in rows:
        source = build_opensearch_source(row, collection_name=collection_name)
        doc_id = opensearch_doc_id(str(source["point_id"]))
        lines.append(json.dumps({"index": {"_index": index_name, "_id": doc_id}}, ensure_ascii=False))
        lines.append(json.dumps(source, ensure_ascii=False))
        count += 1
    body = "\n".join(lines)
    if body:
        body += "\n"
    return body, count


def build_delete_ndjson(
    items: Iterable[dict[str, Any]],
    *,
    index_name: str,
) -> tuple[str, int]:
    lines: list[str] = []
    count = 0
    for item in items:
        point_id = str(item.get("_point_id") or item.get("point_id") or "").strip()
        if not point_id:
            continue
        lines.append(
            json.dumps(
                {"delete": {"_index": index_name, "_id": opensearch_doc_id(point_id)}},
                ensure_ascii=False,
            )
        )
        count += 1
    body = "\n".join(lines)
    if body:
        body += "\n"
    return body, count


def _request(
    method: str,
    url: str,
    *,
    body: str | None = None,
    timeout: float = OPENSEARCH_TIMEOUT_SEC,
    retries: int = 3,
) -> str:
    payload = body.encode("utf-8") if body is not None else None
    request = urllib.request.Request(url=url, method=method, data=payload)
    headers = {"Content-Type": "application/json", **opensearch_auth_headers()}
    for key, value in headers.items():
        request.add_header(key, value)

    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            if attempt >= retries:
                raise RuntimeError(f"HTTP {exc.code} {method} {url}\n{body_text}") from exc
            time.sleep(min(2**attempt, 8))
        except urllib.error.URLError as exc:
            if attempt >= retries:
                raise RuntimeError(f"Network error {method} {url}: {exc}") from exc
            time.sleep(min(2**attempt, 8))


def delete_index_if_exists(index_name: str) -> None:
    url = f"{OPENSEARCH_URL.rstrip('/')}/{urllib.parse.quote(index_name)}"
    try:
        _request("DELETE", url)
    except RuntimeError as exc:
        text = str(exc)
        if "HTTP 404" in text or "index_not_found_exception" in text:
            return
        raise


def create_index_if_missing(index_name: str, *, collection_name: str) -> None:
    url = f"{OPENSEARCH_URL.rstrip('/')}/{urllib.parse.quote(index_name)}"
    body = json.dumps(build_index_payload(collection_name), ensure_ascii=False)
    try:
        _request("PUT", url, body=body)
    except RuntimeError as exc:
        text = str(exc)
        if "resource_already_exists_exception" in text:
            return
        if "Unknown filter type [nori_part_of_speech]" in text:
            fallback_body = json.dumps(build_index_payload(collection_name, enable_nori_pos_filter=False), ensure_ascii=False)
            _request("PUT", url, body=fallback_body)
            return
        if "failed to find tokenizer under name [nori_tokenizer]" in text:
            fallback_body = json.dumps(
                build_index_payload(
                    collection_name,
                    enable_nori_pos_filter=False,
                    tokenizer_name="standard",
                ),
                ensure_ascii=False,
            )
            _request("PUT", url, body=fallback_body)
            return
        raise


def bulk_request(body: str) -> dict[str, Any]:
    if not body.strip():
        return {"errors": False, "items": []}
    raw = _request(
        "POST",
        f"{OPENSEARCH_URL.rstrip('/')}/_bulk",
        body=body,
    )
    payload = json.loads(raw) if raw.strip() else {}
    if not isinstance(payload, dict):
        raise ValueError("OpenSearch bulk response must be an object")
    return payload


def summarize_bulk_result(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items") or []
    success_count = 0
    failure_count = 0
    failures: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            failure_count += 1
            failures.append({"error": "invalid_bulk_item"})
            continue

        op_name, op_payload = next(iter(item.items()))
        if not isinstance(op_payload, dict):
            failure_count += 1
            failures.append({"operation": op_name, "error": "invalid_operation_payload"})
            continue

        status = int(op_payload.get("status") or 0)
        if 200 <= status < 300:
            success_count += 1
            continue

        failure_count += 1
        failures.append(
            {
                "operation": op_name,
                "status": status,
                "error": op_payload.get("error"),
                "id": op_payload.get("_id"),
            }
        )

    return {
        "success_count": success_count,
        "failure_count": failure_count,
        "failures": failures,
        "errors": bool(payload.get("errors")),
    }


def default_batch_size() -> int:
    return BATCH_SIZE
