"""검색 레이어 공통 기반 모듈."""

from __future__ import annotations

import hashlib
import json
import re
import socket
import threading
import urllib.error
import urllib.request
from typing import Any

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_OPENAI_API_BASE_URL = "https://api.openai.com/v1"
# snippet 길이 상수는 qdrant/opensearch 정규화 모듈에서 공통으로 사용한다.
SNIPPET_MAX_LEN = 180

<<<<<<< Updated upstream
_MODEL_CACHE: dict[str, Any] = {}
_MODEL_CACHE_LOCK = threading.RLock()


def is_embedding_model_cached(model_name: str, provider: str = "sentence_transformers") -> bool:
    """현재 프로세스에 임베딩 모델이 메모리 캐시되어 있으면 True.

    OpenAI provider는 로컬 모델 로드가 없으므로 항상 True를 반환한다.
    """
    if provider == "openai":
        return True
    with _MODEL_CACHE_LOCK:
        return model_name in _MODEL_CACHE

=======
>>>>>>> Stashed changes

class RetrievalError(Exception):
    """네트워크·임베딩 등 검색 과정에서 발생하는 오류.

    서비스 레이어에서 발생시키고, CLI 진입점(main)에서만 SystemExit으로 변환한다.
    """


class UpstreamHTTPError(RetrievalError):
    """외부 HTTP API가 4xx/5xx를 반환했을 때 발생한다."""

    def __init__(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        body: str,
    ) -> None:
        body_preview = _safe_http_body_preview(body)
        super().__init__(f"HTTP {status_code} {method} {url}\n{body_preview}")
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body_preview


class UpstreamNetworkError(RetrievalError):
    """외부 API 네트워크 오류."""


class UpstreamTimeoutError(UpstreamNetworkError):
    """외부 API 타임아웃 오류."""


class EmbeddingError(RetrievalError):
    """임베딩 단계 오류."""


class LLMError(RetrievalError):
    """LLM 호출/응답 처리 오류."""


class LLMTimeoutError(LLMError):
    """LLM 호출 타임아웃 오류."""


def _is_timeout_like(exc: object) -> bool:
    """예외 객체가 타임아웃 성격인지 판별한다."""
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def _safe_http_body_preview(body: str, max_chars: int = 1200) -> str:
    """HTTP 오류 본문을 로그/에러 메시지용으로 축약한다."""
    normalized = re.sub(r"\s+", " ", body).strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars]}... [truncated]"


def _sha1_hex(data: bytes) -> str:
    """중복 판별용 SHA-1 해시(FIPS 환경 호환)."""
    try:
        h = hashlib.sha1(data, usedforsecurity=False)  # type: ignore[call-arg]
    except TypeError:
        h = hashlib.sha1(data)
    return h.hexdigest()


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
    현재 retrieval 레이어는 동기 아키텍처이므로 이 함수도 동기 블로킹 I/O로 동작한다.

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
        raise UpstreamHTTPError(
            method=method,
            url=url,
            status_code=int(exc.code),
            body=body,
        ) from exc
    except urllib.error.URLError as exc:
        if _is_timeout_like(getattr(exc, "reason", None)) or _is_timeout_like(exc):
            raise UpstreamTimeoutError(f"Timeout {method} {url}: {exc}") from exc
        raise UpstreamNetworkError(f"Network error {method} {url}: {exc}") from exc
    except TimeoutError as exc:
        raise UpstreamTimeoutError(f"Timeout {method} {url}: {exc}") from exc


# ── 임베딩 ────────────────────────────────────────────────────────────────────

def _embed_query_openai(
    query_text: str,
    model_name: str,
    api_key: str,
    api_base_url: str,
    dimensions: int | None = None,
) -> list[float]:
    """OpenAI Embeddings API를 호출해 벡터를 반환한다."""
    payload: dict[str, Any] = {"model": model_name, "input": query_text}
    if dimensions:
        payload["dimensions"] = dimensions
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        res = http_json("POST", f"{api_base_url}/embeddings", payload, headers, timeout=30)
    except RetrievalError as exc:
        raise EmbeddingError(f"OpenAI 임베딩 호출 실패: {exc}") from exc
    try:
        return list(res["data"][0]["embedding"])
    except (KeyError, IndexError, TypeError) as exc:
        raise EmbeddingError(f"OpenAI 임베딩 응답 파싱 실패: {exc}\n응답: {res}") from exc


def embed_query(
    text: str,
    model_name: str,
    *,
    api_key: str | None,
    api_base_url: str = DEFAULT_OPENAI_API_BASE_URL,
    dimensions: int | None = None,
) -> list[float]:
<<<<<<< Updated upstream
    """텍스트를 임베딩 벡터로 변환한다.

    provider가 'openai'이면 OpenAI Embeddings API를 호출한다.
    그 외(기본값)는 sentence-transformers 로컬 모델을 사용하며,
    모델은 _MODEL_CACHE에 캐싱되어 반복 호출 시 재로드하지 않는다.

    Raises:
        RetrievalError: 패키지 미설치, 빈 텍스트, API 오류 시.
    """
    if not isinstance(text, str):
        raise EmbeddingError(f"질문 텍스트는 문자열이어야 합니다. 현재 타입: {type(text).__name__}")
    query_text = text.strip()
=======
    """텍스트를 Embeddings API로 벡터화한다."""
    if isinstance(text, str):
        query_text = text.strip()
    elif isinstance(text, (list, tuple)):
        query_text = " ".join(str(x) for x in text if x is not None).strip()
    else:
        query_text = str(text).strip()
>>>>>>> Stashed changes

    if not query_text:
        raise EmbeddingError("질문 텍스트가 비어 있습니다.")

<<<<<<< Updated upstream
    if provider == "openai":
        if not api_key:
            raise EmbeddingError("OpenAI 임베딩 사용 시 api_key가 필요합니다.")
        return _embed_query_openai(query_text, model_name, api_key, api_base_url, dimensions)

    # sentence_transformers
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        raise EmbeddingError(
            "sentence-transformers가 필요합니다.\n설치: uv add sentence-transformers"
        ) from exc

    with _MODEL_CACHE_LOCK:
        model = _MODEL_CACHE.get(model_name)
    if model is None:
        try:
            model = SentenceTransformer(model_name)
        except Exception as exc:
            raise EmbeddingError(
                "임베딩 모델 로드 실패: EMBEDDING_MODEL/네트워크 상태를 확인하세요.\n"
                f"현재 EMBEDDING_MODEL={model_name}\n"
                f"원인: {type(exc).__name__}: {exc}"
            ) from exc
        with _MODEL_CACHE_LOCK:
            _MODEL_CACHE[model_name] = model

    try:
        vec = model.encode([query_text], normalize_embeddings=True)
    except TypeError as first_exc:
        # 간헐적 tokenizer 타입 오류 대응: 모델 재로딩 후 1회 재시도
        with _MODEL_CACHE_LOCK:
            _MODEL_CACHE.pop(model_name, None)
        try:
            model = SentenceTransformer(model_name)
            with _MODEL_CACHE_LOCK:
                _MODEL_CACHE[model_name] = model
            vec = model.encode(
                [query_text.replace("\x00", " ").strip()],
                normalize_embeddings=True,
            )
        except Exception as retry_exc:
            raise EmbeddingError(
                "임베딩 모델 토크나이징 실패: EMBEDDING_MODEL이 문장 임베딩용 모델인지 확인하세요.\n"
                f"현재 EMBEDDING_MODEL={model_name}\n"
                f"1차 오류: {type(first_exc).__name__}: {first_exc}\n"
                f"원인: {type(retry_exc).__name__}: {retry_exc}"
            ) from retry_exc
    except Exception as exc:
        raise EmbeddingError(
            "임베딩 생성 실패: model.encode 호출 중 예외가 발생했습니다.\n"
            f"현재 EMBEDDING_MODEL={model_name}\n"
            f"원인: {type(exc).__name__}: {exc}"
        ) from exc

    if hasattr(vec, "tolist"):
        arr = vec.tolist()
        if isinstance(arr, list) and arr and isinstance(arr[0], list):
            return list(arr[0])
        return list(arr)
    if isinstance(vec, list) and vec and isinstance(vec[0], list):
        return list(vec[0])
    return list(vec)
=======
    if not api_key:
        raise RetrievalError("OPENAI_API_KEY가 필요합니다.")
    return _embed_query_openai(query_text, model_name, api_key, api_base_url, dimensions)
>>>>>>> Stashed changes


# ── 중복 제거 ─────────────────────────────────────────────────────────────────

def normalize_source_id(source_id: str) -> str:
    """source_id 끝의 중복 suffix(__dup0, __dup1 …)를 제거해 정규화한다."""
    if not source_id:
        return ""
    return re.sub(r"__dup\d+$", "", source_id)


def _fallback_text_key(text: str) -> str:
    """source_id가 없을 때 텍스트 앞 800자의 SHA-1 해시를 중복 판별 키로 사용한다."""
    text_norm = re.sub(r"\s+", " ", text).strip().lower()
    digest = _sha1_hex(text_norm[:800].encode("utf-8"))
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
