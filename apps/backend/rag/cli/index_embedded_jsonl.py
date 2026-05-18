#!/usr/bin/env python3
"""Index pre-embedded JSONL into Qdrant and OpenSearch.

[빠른 실행 방법]
1) 환경변수 로드
   cd apps/backend
   cp .env.example .env
2) 인덱싱 실행
   uv run python cli/index_embedded_jsonl.py --batch-size 256
3) 업로드 없이 입력 확인만
   uv run python cli/index_embedded_jsonl.py --dry-run --limit 100

Expected JSONL row (example):
{
  "point_id": "law::...",
  "vector": [...],
  "payload": {...},
  "text_for_embedding": "...",
  "embedding_model": "...",
  "embedding_dim": 384
}
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from rag_pipeline.env_config import load_backend_env

load_backend_env()


@dataclass
class EmbeddedDoc:
    point_id: str
    vector: list[float]
    payload: dict[str, Any]
    text: str
    embedding_model: str | None
    embedding_dim: int | None


def require_env(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val


def http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout: int,
    retries: int = 3,
) -> dict[str, Any]:
    req = urllib.request.Request(
        url=url,
        method=method,
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    for k, v in headers.items():
        req.add_header(k, v)

    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if attempt >= retries:
                raise SystemExit(f"HTTP {exc.code} {method} {url}\n{body}") from exc
            time.sleep(min(2**attempt, 8))
        except urllib.error.URLError as exc:
            if attempt >= retries:
                raise SystemExit(f"Network error {method} {url}: {exc}") from exc
            time.sleep(min(2**attempt, 8))


def http_text(
    method: str,
    url: str,
    headers: dict[str, str],
    body: str,
    timeout: int,
    retries: int = 3,
) -> str:
    req = urllib.request.Request(url=url, method=method, data=body.encode("utf-8"))
    for k, v in headers.items():
        req.add_header(k, v)

    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if attempt >= retries:
                raise SystemExit(f"HTTP {exc.code} {method} {url}\n{body}") from exc
            time.sleep(min(2**attempt, 8))
        except urllib.error.URLError as exc:
            if attempt >= retries:
                raise SystemExit(f"Network error {method} {url}: {exc}") from exc
            time.sleep(min(2**attempt, 8))


def qdrant_numeric_id(point_id: str) -> int:
    digest = hashlib.sha1(point_id.encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)


def opensearch_doc_id(point_id: str, max_bytes: int = 512) -> str:
    raw = point_id.encode("utf-8")
    if len(raw) <= max_bytes:
        return point_id
    # Preserve stable/idempotent indexing when source id exceeds OpenSearch _id limit.
    return f"sha1::{hashlib.sha1(raw).hexdigest()}"


def parse_doc(obj: dict[str, Any], source: Path, line_no: int) -> EmbeddedDoc:
    point_id = str(obj.get("point_id") or obj.get("id") or "").strip()
    if not point_id:
        raise SystemExit(f"Missing point_id at {source}:{line_no}")

    vector = obj.get("vector")
    if not isinstance(vector, list) or not vector:
        raise SystemExit(f"Missing/invalid vector at {source}:{line_no}")

    payload = obj.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    text = str(obj.get("text_for_embedding") or obj.get("text") or "")
    embedding_model = obj.get("embedding_model")
    embedding_dim = obj.get("embedding_dim")
    if embedding_dim is not None:
        try:
            embedding_dim = int(embedding_dim)
        except (TypeError, ValueError):
            embedding_dim = None

    return EmbeddedDoc(
        point_id=point_id,
        vector=vector,
        payload=payload,
        text=text,
        embedding_model=embedding_model if isinstance(embedding_model, str) else None,
        embedding_dim=embedding_dim,
    )


def read_embedded_jsonl(files: list[Path], limit: int | None = None) -> Iterator[EmbeddedDoc]:
    count = 0
    for path in files:
        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"Invalid JSON at {path}:{line_no}: {exc}") from exc
                yield parse_doc(obj, path, line_no)
                count += 1
                if limit is not None and count >= limit:
                    return


def batched[T](items: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def discover_files(input_glob: str) -> list[Path]:
    files = sorted([p for p in Path().glob(input_glob) if p.is_file() and p.suffix == ".jsonl"])
    if not files:
        raise SystemExit(f"No JSONL files matched: {input_glob}")
    return files


def qdrant_upsert(
    docs: list[EmbeddedDoc],
    *,
    qdrant_url: str,
    collection: str,
    api_key: str | None,
    timeout: int,
) -> None:
    points: list[dict[str, Any]] = []
    for d in docs:
        payload = {
            **d.payload,
            "source_id": d.point_id,
            "text": d.text,
            "embedding_model": d.embedding_model,
            "embedding_dim": d.embedding_dim,
        }
        points.append({"id": qdrant_numeric_id(d.point_id), "vector": d.vector, "payload": payload})

    url = f"{qdrant_url.rstrip('/')}/collections/{urllib.parse.quote(collection)}/points?wait=true"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    http_json("PUT", url, headers, {"points": points}, timeout)


def qdrant_create_collection_if_missing(
    *,
    qdrant_url: str,
    collection: str,
    vector_size: int,
    distance: str,
    api_key: str | None,
    timeout: int,
) -> None:
    distance_map = {
        "cosine": "Cosine",
        "dot": "Dot",
        "euclid": "Euclid",
        "manhattan": "Manhattan",
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    url = f"{qdrant_url.rstrip('/')}/collections/{urllib.parse.quote(collection)}"
    payload = {
        "vectors": {
            "size": vector_size,
            "distance": distance_map[distance],
        }
    }

    req = urllib.request.Request(
        url=url,
        method="PUT",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        # Collection already exists -> treat as success.
        if exc.code == 409:
            return
        raise SystemExit(f"HTTP {exc.code} PUT {url}\n{body}") from exc


def opensearch_auth_headers() -> dict[str, str]:
    api_key = os.getenv("OPENSEARCH_API_KEY", "").strip()
    if api_key:
        return {"Authorization": f"ApiKey {api_key}"}

    user = os.getenv("OPENSEARCH_USERNAME", "").strip()
    pw = os.getenv("OPENSEARCH_PASSWORD", "").strip()
    if user and pw:
        token = base64.b64encode(f"{user}:{pw}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}
    return {}


def opensearch_bulk(
    docs: list[EmbeddedDoc],
    *,
    opensearch_url: str,
    index_name: str,
    vector_field: str | None,
    timeout: int,
) -> tuple[int, int]:
    headers = {
        "Content-Type": "application/x-ndjson",
        **opensearch_auth_headers(),
    }

    lines: list[str] = []
    for d in docs:
        meta = {"index": {"_index": index_name, "_id": opensearch_doc_id(d.point_id)}}
        src: dict[str, Any] = {
            **d.payload,
            "id": d.point_id,
            "text": d.text,
            "embedding_model": d.embedding_model,
            "embedding_dim": d.embedding_dim,
        }
        if vector_field:
            src[vector_field] = d.vector
        lines.append(json.dumps(meta, ensure_ascii=False))
        lines.append(json.dumps(src, ensure_ascii=False))

    raw = http_text(
        "POST",
        f"{opensearch_url.rstrip('/')}/_bulk",
        headers,
        "\n".join(lines) + "\n",
        timeout,
    )

    try:
        res = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"OpenSearch bulk non-JSON response: {raw[:500]}") from exc

    items = res.get("items", [])
    ok = 0
    fail = 0
    for item in items:
        idx = item.get("index", {}) if isinstance(item, dict) else {}
        status = idx.get("status", 500)
        if isinstance(status, int) and 200 <= status < 300:
            ok += 1
        else:
            fail += 1
    return ok, fail


def opensearch_create_index_if_missing(
    *,
    opensearch_url: str,
    index_name: str,
    vector_field: str | None,
    vector_dim: int,
    timeout: int,
) -> None:
    if vector_dim <= 0:
        raise SystemExit("Invalid vector dimension for OpenSearch mapping creation")

    headers = {
        "Content-Type": "application/json",
        **opensearch_auth_headers(),
    }

    properties: dict[str, Any] = {
        "id": {"type": "keyword"},
        "text": {"type": "text"},
        "doc_type": {"type": "keyword"},
        "law_name": {"type": "keyword"},
        "source_group": {"type": "keyword"},
        "source_file_path": {"type": "keyword"},
        "embedding_model": {"type": "keyword"},
        "embedding_dim": {"type": "integer"},
        "article_no": {"type": "keyword"},
        "jo_code": {"type": "keyword"},
        "doc_id": {"type": "keyword"},
        "title": {"type": "text"},
        "doc_number": {"type": "keyword"},
    }
    if vector_field:
        # Store vectors as numeric arrays for inspection/debug use.
        properties[vector_field] = {"type": "float"}

    payload: dict[str, Any] = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "dynamic": True,
            "properties": properties,
        },
    }
    url = f"{opensearch_url.rstrip('/')}/{urllib.parse.quote(index_name)}"
    req = urllib.request.Request(
        url=url,
        method="PUT",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        # Index already exists -> treat as success.
        if exc.code == 400 and "resource_already_exists_exception" in body:
            return
        raise SystemExit(f"HTTP {exc.code} PUT {url}\n{body}") from exc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Index pre-embedded JSONL into Qdrant/OpenSearch")
    p.add_argument("--input-glob", default="data/dropbox/*.embedded.jsonl")
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--opensearch-vector-field",
        default="",
        help="OpenSearch에 벡터 저장 시 필드명 (예: embedding). 비우면 벡터 미저장",
    )
    p.add_argument("--dry-run", action="store_true", help="업로드 없이 파싱/배치만 검증")
    p.add_argument(
        "--qdrant-distance",
        default="cosine",
        choices=["cosine", "dot", "euclid", "manhattan"],
        help="컬렉션 자동 생성 시 사용할 Qdrant distance",
    )
    p.add_argument(
        "--no-create-collection",
        action="store_true",
        help="Qdrant 컬렉션 자동 생성을 비활성화",
    )
    p.add_argument(
        "--no-create-opensearch-index",
        action="store_true",
        help="OpenSearch 인덱스/매핑 자동 생성을 비활성화",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be > 0")

    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    qdrant_collections = [
        item.strip()
        for item in os.getenv("QDRANT_COLLECTIONS", "").split(",")
        if item.strip()
    ]
    qdrant_collection = qdrant_collections[0] if qdrant_collections else ""
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip() or None

    opensearch_url = os.getenv("OPENSEARCH_URL", "").strip()
    opensearch_index = os.getenv("OPENSEARCH_INDEX", "").strip()
    if not args.dry_run:
        if not qdrant_url:
            raise SystemExit("Missing required env var: QDRANT_URL")
        if not qdrant_collection:
            raise SystemExit("Missing required env var: QDRANT_COLLECTIONS")
        if not opensearch_url:
            raise SystemExit("Missing required env var: OPENSEARCH_URL")
        if not opensearch_index:
            raise SystemExit("Missing required env var: OPENSEARCH_INDEX")

    files = discover_files(args.input_glob)
    total = 0
    qdrant_total = 0
    os_ok_total = 0
    os_fail_total = 0
    ensured_collection = False
    ensured_opensearch_index = False

    print(f"[INFO] files={len(files)}")
    for f in files:
        print(f"  - {f}")

    for idx, batch in enumerate(batched(read_embedded_jsonl(files, args.limit), args.batch_size), start=1):
        total += len(batch)

        if not args.dry_run:
            if not ensured_collection and not args.no_create_collection:
                qdrant_create_collection_if_missing(
                    qdrant_url=qdrant_url,
                    collection=qdrant_collection,
                    vector_size=len(batch[0].vector),
                    distance=args.qdrant_distance,
                    api_key=qdrant_api_key,
                    timeout=args.timeout,
                )
                ensured_collection = True
            if not ensured_opensearch_index and not args.no_create_opensearch_index:
                opensearch_create_index_if_missing(
                    opensearch_url=opensearch_url,
                    index_name=opensearch_index,
                    vector_field=(args.opensearch_vector_field.strip() or None),
                    vector_dim=len(batch[0].vector),
                    timeout=args.timeout,
                )
                ensured_opensearch_index = True
            qdrant_upsert(
                batch,
                qdrant_url=qdrant_url,
                collection=qdrant_collection,
                api_key=qdrant_api_key,
                timeout=args.timeout,
            )
            qdrant_total += len(batch)

            ok, fail = opensearch_bulk(
                batch,
                opensearch_url=opensearch_url,
                index_name=opensearch_index,
                vector_field=(args.opensearch_vector_field.strip() or None),
                timeout=args.timeout,
            )
            os_ok_total += ok
            os_fail_total += fail

        print(
            f"[BATCH {idx}] docs={len(batch)} total={total} "
            f"qdrant={qdrant_total} os_ok={os_ok_total} os_fail={os_fail_total}"
        )

    print("[DONE]")
    print(f"  total={total}")
    print(f"  qdrant_upserted={qdrant_total}")
    print(f"  opensearch_success={os_ok_total}")
    print(f"  opensearch_failure={os_fail_total}")


if __name__ == "__main__":
    main()
