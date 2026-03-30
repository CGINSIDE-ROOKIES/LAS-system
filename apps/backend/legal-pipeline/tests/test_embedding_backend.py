import numpy as np
import httpx

from src.common.embedding_backend import OpenAIEmbeddingBackend, load_embedding_settings


class _FakeResponse:
    text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "data": [
                {"index": 1, "embedding": [0.0, 3.0, 4.0]},
                {"index": 0, "embedding": [3.0, 4.0, 0.0]},
            ]
        }


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls: list[dict] = []

    def post(self, path: str, json: dict) -> _FakeResponse:
        self.calls.append({"path": path, "json": json})
        return _FakeResponse()

    def close(self) -> None:
        return None


class _RetryResponse:
    def __init__(self, *, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"error {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request, text=self.text),
            )

    def json(self) -> dict:
        return self._payload


class _RetryClient:
    def __init__(self, *args, **kwargs):
        self.calls: list[dict] = []
        self._responses = [
            _RetryResponse(status_code=500, text='{"error":{"message":"server error"}}'),
            _RetryResponse(
                status_code=200,
                payload={
                    "data": [
                        {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                    ]
                },
            ),
        ]

    def post(self, path: str, json: dict):
        self.calls.append({"path": path, "json": json})
        return self._responses.pop(0)

    def close(self) -> None:
        return None


def test_load_embedding_settings_for_openai(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("OPENAI_EMBEDDING_DIMENSIONS", "1024")

    settings = load_embedding_settings()

    assert settings.provider == "openai"
    assert settings.model_name == "text-embedding-3-large"
    assert settings.openai_dimensions == 1024
    assert settings.device_mode == "remote_api"


def test_openai_backend_encodes_and_normalizes(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("OPENAI_EMBEDDING_DIMENSIONS", "3")
    monkeypatch.setattr("src.common.embedding_backend.httpx.Client", _FakeClient)

    backend = OpenAIEmbeddingBackend(load_embedding_settings())
    try:
        vectors = backend.encode(["alpha", "beta"], batch_size=16)
    finally:
        backend.close()

    assert vectors.shape == (2, 3)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-6)


def test_openai_backend_truncates_and_splits_batches(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("OPENAI_MAX_INPUT_TOKENS", "4")
    monkeypatch.setenv("OPENAI_MAX_BATCH_TOKENS", "5")
    monkeypatch.setattr("src.common.embedding_backend.httpx.Client", _FakeClient)

    backend = OpenAIEmbeddingBackend(load_embedding_settings())
    monkeypatch.setattr(backend, "_encode_token_count", lambda text: len(text))
    monkeypatch.setattr(backend, "_truncate_text", lambda text: text[:4])

    try:
        backend.encode(["abcd", "efgh", "ijkl"], batch_size=8)
    finally:
        backend.close()

    calls = backend._client.calls
    assert len(calls) == 3
    assert calls[0]["json"]["input"] == ["abcd"]
    assert calls[1]["json"]["input"] == ["efgh"]
    assert calls[2]["json"]["input"] == ["ijkl"]


def test_openai_backend_retries_retryable_status(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "2")
    monkeypatch.setattr("src.common.embedding_backend.httpx.Client", _RetryClient)
    monkeypatch.setattr("src.common.embedding_backend.time.sleep", lambda _delay: None)

    backend = OpenAIEmbeddingBackend(load_embedding_settings())
    try:
        vectors = backend.encode(["alpha"], batch_size=8)
    finally:
        backend.close()

    assert vectors.shape == (1, 3)
    assert len(backend._client.calls) == 2
