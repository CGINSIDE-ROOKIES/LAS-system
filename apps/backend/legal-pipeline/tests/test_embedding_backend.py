import numpy as np

from src.common.embedding_backend import OpenAIEmbeddingBackend, load_embedding_settings


class _FakeResponse:
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
