from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_EMBEDDING_API_BASE_URL = "https://api.openai.com/v1"

# 결과 snippet 최대 길이 (모든 normalize 함수에서 공통 사용)
SNIPPET_MAX_LEN = 180

class RetrievalError(Exception):
    """네트워크·임베딩 등 검색 과정에서 발생하는 오류.

    라이브러리로 재사용할 때 SystemExit 대신 이 예외를 잡아 처리한다.
    CLI 진입점(main)에서만 SystemExit으로 변환한다.
    """


# ── 설정값 읽기 ───────────────────────────────────────────────────────────────
def require_env_or_arg(
    value: str | None, env_name: str, fallback: str | None = None
) -> str:
    """CLI 인자 → 환경변수 → fallback 순으로 설정값을 읽는다.

    Args:
        value:    CLI 인자로 전달된 값 (없으면 None 또는 빈 문자열).
        env_name: 환경변수 이름 (예: "QDRANT_URL").
        fallback: 위 두 값이 모두 없을 때 사용할 기본값.

    Returns:
        공백·CR 제거된 설정값 문자열.

    Raises:
        SystemExit: fallback도 없는 필수 값이 누락된 경우.
    """

    def _clean(v: str) -> str:
        # Windows CRLF 및 앞뒤 공백 제거
        return v.replace("\r", "").strip()

    # 1순위: CLI 인자
    if value is not None:
        value_clean = _clean(value)
        if value_clean:
            return value_clean

    # 2순위: 환경 변수
    env_val = _clean(os.getenv(env_name, ""))
    if env_val:
        return env_val

    # 3순위: 호출자가 지정한 기본값
    if fallback is not None:
        return _clean(fallback)

    # 필수값인데 모두 없으면 종료
    raise SystemExit(
        f"Missing required setting: --{env_name.lower().replace('_', '-')} or {env_name}"
    )


# ── HTTP 유틸리티 ─────────────────────────────────────────────────────────────
def http_json(
    method: str,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    """JSON payload를 전송하고 응답 JSON을 반환하는 범용 HTTP 클라이언트.

    외부 라이브러리(requests 등) 없이 표준 라이브러리만 사용한다.

    Raises:
        RetrievalError: HTTP 오류(4xx/5xx) 또는 네트워크 오류 발생 시.
    """
    req = urllib.request.Request(
        url=url,
        method=method,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    for k, v in headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RetrievalError(f"HTTP {exc.code} {method} {url}\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RetrievalError(f"Network error {method} {url}: {exc}") from exc


# ── 텍스트 임베딩 ─────────────────────────────────────────────────────────────
def _embed_query_openai(
    query_text: str,
    model_name: str,
    api_key: str,
    api_base_url: str,
    dimensions: int | None = None,
) -> list[float]:
    payload: dict[str, Any] = {"model": model_name, "input": query_text}
    if dimensions is not None:
        payload["dimensions"] = dimensions
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    res = http_json("POST", f"{api_base_url}/embeddings", payload, headers, timeout=30)
    try:
        return list(res["data"][0]["embedding"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RetrievalError(f"Embedding API 응답 파싱 실패: {exc}\n응답: {res}") from exc


def embed_query(text: str, model_name: str) -> list[float]:
    """텍스트를 Embeddings API로 벡터화한다."""
    if isinstance(text, str):
        query_text = text.strip()
    elif isinstance(text, (list, tuple)):
        query_text = " ".join(str(x) for x in text if x is not None).strip()
    else:
        query_text = str(text).strip()

    if not query_text:
        raise RetrievalError("질문 텍스트가 비어 있습니다.")

    api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
    if not api_key:
        raise RetrievalError("EMBEDDING_API_KEY가 필요합니다.")
    api_base_url = (
        os.getenv("EMBEDDING_BASE_URL", "").strip()
        or DEFAULT_EMBEDDING_API_BASE_URL
    )
    raw_dimensions = os.getenv("EMBEDDING_DIMENSIONS", "").strip()
    dimensions = int(raw_dimensions) if raw_dimensions else None
    return _embed_query_openai(query_text, model_name, api_key, api_base_url.rstrip("/"), dimensions)


def _fallback_text_key(text: str) -> str:
    # source_id가 없을 때 텍스트 앞 800자의 SHA-1 해시를 중복 판별 키로 사용한다.
    text_norm = re.sub(r"\s+", " ", text).strip().lower()
    digest = hashlib.sha1(text_norm[:800].encode("utf-8")).hexdigest()
    return f"text::{digest}"


def dedup_normalized_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """정규화된 source_id 기준으로 중복 행을 제거한다.

    source_id가 없으면 텍스트 해시를 fallback 키로 사용한다.
    입력 순서(= 점수 내림차순)를 유지하며, 처음 등장한 행만 남긴다.
    """
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rows:
        sid = str(row.get("source_id", "") or "")
        key = sid
        if not key:
            key = _fallback_text_key(str(row.get("text", "") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


# ── Qdrant 결과 정규화 ────────────────────────────────────────────────────────
def _normalize_qdrant_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Qdrant 검색 결과를 공통 포맷(rank, score, source_id 등)으로 변환한다.

    snippet은 개행 제거 후 최대 180자로 잘라낸 미리보기 텍스트다.
    """
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        payload = row.get("payload") or {}
        text = str(payload.get("text", "") or "")
        out.append(
            {
                "rank": i,
                "score": row.get("score"),
                "source_id": payload.get("id", ""),
                "doc_type": payload.get("doc_type", ""),
                "law_name": payload.get("law_name", ""),
                "text": text,
                "snippet": text.replace("\n", " ")[:SNIPPET_MAX_LEN],
            }
        )
    return out


# ── BM25(OpenSearch) 결과 정규화 ─────────────────────────────────────────────
def _normalize_bm25_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenSearch BM25 검색 결과를 공통 포맷으로 변환한다.

    OpenSearch는 `_source` / `_score` 필드명을 사용하므로 Qdrant와 다르게 처리한다.
    """
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        src = row.get("_source") or {}
        text = str(src.get("text", "") or "")
        out.append(
            {
                "rank": i,
                "score": row.get("_score"),
                "source_id": src.get("id", ""),
                "doc_type": src.get("doc_type", ""),
                "law_name": src.get("law_name", ""),
                "text": text,
                "snippet": text.replace("\n", " ")[:SNIPPET_MAX_LEN],
            }
        )
    return out


# ── Qdrant 필터 빌더 ──────────────────────────────────────────────────────────
def _build_qdrant_filter(
    doc_types: list[str] | None, law_names: list[str] | None
) -> dict[str, Any] | None:
    """doc_type / law_name 필터 조건을 Qdrant payload filter 형식으로 생성한다.

    두 조건 모두 없으면 None을 반환 (필터 미적용).
    """
    must: list[dict[str, Any]] = []
    if doc_types:
        must.append({"key": "doc_type", "match": {"any": doc_types}})
    if law_names:
        must.append({"key": "law_name", "match": {"any": law_names}})
    return {"must": must} if must else None


# ── Qdrant 밀집(dense) 벡터 검색 ─────────────────────────────────────────────
def search_qdrant(
    query: str,
    top_k: int,
    *,
    qdrant_url: str,
    collection: str,
    timeout: int,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    api_key: str | None = None,
    doc_types: list[str] | None = None,
    law_names: list[str] | None = None,
    dedup: bool = True,
    fetch_multiplier: int = 2,
    vector_name: str | None = "body",
) -> list[dict[str, Any]]:
    """쿼리를 임베딩 후 Qdrant에서 유사 문서 Top-K를 검색한다.

    dedup=True일 경우 top_k * fetch_multiplier 만큼 먼저 가져온 뒤
    중복 제거 후 top_k개로 잘라낸다.

    Args:
        query:            검색 질문 텍스트.
        top_k:            최종 반환할 결과 수.
        qdrant_url:       Qdrant 서버 주소.
        collection:       검색할 컬렉션 이름.
        timeout:          요청 타임아웃(초).
        embedding_model:  사용할 임베딩 모델 이름.
        api_key:          Qdrant API 키 (없으면 None).
        doc_types:        doc_type 필터 값 목록 (없으면 전체).
        law_names:        law_name 필터 값 목록 (없으면 전체).
        dedup:            중복 문서 제거 여부.
        fetch_multiplier: dedup 여유분을 위해 top_k에 곱할 배수.

    Returns:
        공통 포맷의 결과 딕셔너리 리스트 (rank, score, source_id 등 포함).
    """
    # 1. 질문을 벡터로 변환
    vector = embed_query(query, embedding_model)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    # dedup 여유분 확보: 중복 제거 후에도 top-k개가 남도록 넉넉히 요청
    fetch_limit = max(1, top_k * max(1, fetch_multiplier)) if dedup else max(1, top_k)
    payload: dict[str, Any] = {
        "vector": {"name": vector_name, "vector": vector} if vector_name else vector,
        "limit": fetch_limit,
        "with_payload": True,  # 메타데이터(text, doc_type 등) 포함
        "with_vector": False,  # 벡터값은 응답에 불필요
    }
    filt = _build_qdrant_filter(doc_types, law_names)
    if filt:
        payload["filter"] = filt

    # 2. Qdrant REST API 호출
    url = f"{qdrant_url.rstrip('/')}/collections/{urllib.parse.quote(collection)}/points/search"
    res = http_json("POST", url, payload, headers, timeout)
    raw_rows = res.get("result", [])
    if not isinstance(raw_rows, list):
        return []

    # 3. 공통 포맷으로 변환 -> 중복 제거 -> top_k개로 자르기
    rows = _normalize_qdrant_results(raw_rows)
    if dedup:
        rows = dedup_normalized_rows(rows)

    trimmed = rows[: max(1, top_k)]
    for i, row in enumerate(trimmed, start=1):
        row["rank"] = i  # 중복 제거 후 rank 재부여
    return trimmed


# ── OpenSearch 인증 헤더 빌더 ─────────────────────────────────────────────────
def _opensearch_auth_header(
    api_key: str | None, username: str | None, password: str | None
) -> dict[str, str]:
    # API 키 > Basic 인증 > 인증 없음 순으로 Authorization 헤더를 반환
    if api_key:
        return {"Authorization": f"ApiKey {api_key}"}
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
            "ascii"
        )
        return {"Authorization": f"Basic {token}"}
    return {}


# ── BM25 쿼리 빌더 ────────────────────────────────────────────────────────────
def _build_bm25_query(
    query: str, top_k: int, doc_types: list[str] | None, law_names: list[str] | None
) -> dict[str, Any]:
    """OpenSearch BM25 검색용 쿼리 DSL을 생성한다.

    `search_text` 필드(법령명+조문번호+본문 통합)에 OR 매칭을 적용하고, doc_type / law_name 조건은 filter로 추가한다.
    filter는 점수에 영향을 주지 않고 후보를 사전 제한하는 역할만 한다.
    """
    # BM25 본문 매칭 조건 (OR: 단어 하나라도 포함되면 후보로 취급)
    must: list[dict[str, Any]] = [
        {
            "match": {
                "search_text": {
                    "query": query,
                    "operator": "or",
                }
            }
        }
    ]
    filters: list[dict[str, Any]] = []

    if doc_types:
        filters.append({"terms": {"doc_type": doc_types}})
    if law_names:
        filters.append({"terms": {"law_name": law_names}})

    query_obj: dict[str, Any] = {"bool": {"must": must}}
    if filters:
        query_obj["bool"]["filter"] = filters

    return {
        "size": max(1, top_k),
        "query": query_obj,
        "_source": True,  # 전체 source 반환
    }


# ── BM25(OpenSearch) 키워드 검색 ─────────────────────────────────────────────
def search_bm25(
    query: str,
    top_k: int,
    *,
    opensearch_url: str,
    index_name: str,
    timeout: int,
    api_key: str | None = None,
    username: str | None = None,
    password: str | None = None,
    doc_types: list[str] | None = None,
    law_names: list[str] | None = None,
    dedup: bool = True,
    fetch_multiplier: int = 5,  # BM25는 키워드 중복이 많아 Qdrant보다 배수를 높게 설정
) -> list[dict[str, Any]]:
    """OpenSearch에서 BM25 키워드 검색으로 Top-K 문서를 반환한다.

    search_qdrant와 동일한 공통 포맷으로 결과를 반환하므로
    두 결과를 병합(hybrid search)하기 쉽다.

    Args:
        query:            검색 질문 텍스트.
        top_k:            최종 반환할 결과 수.
        opensearch_url:   OpenSearch 클러스터 주소.
        index_name:       검색할 인덱스 이름.
        timeout:          요청 타임아웃(초).
        api_key:          API 키 인증 (username/password보다 우선).
        username:         Basic 인증 사용자명.
        password:         Basic 인증 비밀번호.
        doc_types:        doc_type 필터.
        law_names:        law_name 필터.
        dedup:            중복 문서 제거 여부.
        fetch_multiplier: dedup 여유분 배수 (기본 5).

    Returns:
        공통 포맷의 결과 딕셔너리 리스트.
    """
    headers = {
        "Content-Type": "application/json",
        **_opensearch_auth_header(api_key, username, password),
    }

    fetch_k = max(1, top_k * max(1, fetch_multiplier)) if dedup else max(1, top_k)
    payload = _build_bm25_query(query, fetch_k, doc_types, law_names)

    url = f"{opensearch_url.rstrip('/')}/{urllib.parse.quote(index_name)}/_search"
    res = http_json("POST", url, payload, headers, timeout)
    hits = (res.get("hits") or {}).get("hits") or []
    if not isinstance(hits, list):
        return []

    rows = _normalize_bm25_results(hits)
    if dedup:
        rows = dedup_normalized_rows(rows)

    trimmed = rows[: max(1, top_k)]
    for i, row in enumerate(trimmed, start=1):
        row["rank"] = i
    return trimmed
