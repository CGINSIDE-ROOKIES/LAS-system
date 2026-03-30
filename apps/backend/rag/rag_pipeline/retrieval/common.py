"""검색 레이어 공통 기반 모듈.

포함 내용:
  - RetrievalError: 검색 과정 예외
  - http_json: 표준 라이브러리 기반 HTTP 클라이언트
  - embed_query: 텍스트 임베딩
  - normalize_source_id / dedup_normalized_rows: 중복 제거 유틸리티
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
SNIPPET_MAX_LEN = 180

_MODEL_CACHE: dict[str, Any] = {}


def is_embedding_model_cached(model_name: str) -> bool:
    """현재 프로세스에 임베딩 모델이 메모리 캐시되어 있으면 True."""
    return model_name in _MODEL_CACHE


class RetrievalError(Exception):
    """네트워크·임베딩 등 검색 과정에서 발생하는 오류.

    서비스 레이어에서 발생시키고, CLI 진입점(main)에서만 SystemExit으로 변환한다.
    """


# ── HTTP ──────────────────────────────────────────────────────────────────────

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


# ── 임베딩 ────────────────────────────────────────────────────────────────────

def embed_query(text: str, model_name: str) -> list[float]:
    """텍스트를 임베딩 벡터로 변환한다.

    모델은 _MODEL_CACHE에 캐싱되어 반복 호출 시 재로드하지 않는다.

    Raises:
        RetrievalError: 패키지 미설치, 빈 텍스트, 토크나이징 실패 시.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        raise RetrievalError(
            "sentence-transformers가 필요합니다.\n설치: uv add sentence-transformers"
        ) from exc

    if isinstance(text, str):
        query_text = text.strip()
    elif isinstance(text, (list, tuple)):
        query_text = " ".join(str(x) for x in text if x is not None).strip()
    else:
        query_text = str(text).strip()

    if not query_text:
        raise RetrievalError("질문 텍스트가 비어 있습니다.")

    model = _MODEL_CACHE.get(model_name)
    if model is None:
        try:
            model = SentenceTransformer(model_name)
        except Exception as exc:
            raise RetrievalError(
                "임베딩 모델 로드 실패: EMBEDDING_MODEL/네트워크 상태를 확인하세요.\n"
                f"현재 EMBEDDING_MODEL={model_name}\n"
                f"원인: {type(exc).__name__}: {exc}"
            ) from exc
        _MODEL_CACHE[model_name] = model

    query_text = str(query_text)
    try:
        vec = model.encode([query_text], normalize_embeddings=True)
    except TypeError:
        # 간헐적 tokenizer 타입 오류 대응: 모델 재로딩 후 1회 재시도
        _MODEL_CACHE.pop(model_name, None)
        try:
            model = SentenceTransformer(model_name)
            _MODEL_CACHE[model_name] = model
            vec = model.encode(
                [query_text.replace("\x00", " ").strip()],
                normalize_embeddings=True,
            )
        except Exception as retry_exc:
            raise RetrievalError(
                "임베딩 모델 토크나이징 실패: EMBEDDING_MODEL이 문장 임베딩용 모델인지 확인하세요.\n"
                f"현재 EMBEDDING_MODEL={model_name}\n"
                f"원인: {type(retry_exc).__name__}: {retry_exc}"
            ) from retry_exc

    if hasattr(vec, "tolist"):
        arr = vec.tolist()
        if isinstance(arr, list) and arr and isinstance(arr[0], list):
            return list(arr[0])
        return list(arr)
    if isinstance(vec, list) and vec and isinstance(vec[0], list):
        return list(vec[0])
    return list(vec)


# ── 중복 제거 ─────────────────────────────────────────────────────────────────

def normalize_source_id(source_id: str) -> str:
    """source_id 끝의 중복 suffix(__dup0, __dup1 …)를 제거해 정규화한다."""
    if not source_id:
        return ""
    return re.sub(r"__dup\d+$", "", source_id)


def _fallback_text_key(text: str) -> str:
    """source_id가 없을 때 텍스트 앞 800자의 SHA-1 해시를 중복 판별 키로 사용한다."""
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
        key = normalize_source_id(sid) if sid else ""
        if not key:
            key = _fallback_text_key(str(row.get("text", "") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
