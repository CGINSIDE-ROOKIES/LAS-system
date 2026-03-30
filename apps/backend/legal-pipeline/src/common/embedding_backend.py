from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
import numpy as np
import tiktoken
import torch
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_SENTENCE_TRANSFORMER_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CPU_WORKERS = 4
DEFAULT_OPENAI_MAX_INPUT_TOKENS = 8192
DEFAULT_OPENAI_MAX_BATCH_TOKENS = 300000
DEFAULT_OPENAI_MAX_RETRIES = 5
DEFAULT_OPENAI_RETRY_BASE_DELAY_SEC = 1.0
NORMALIZE_EMBEDDINGS = True
EMBEDDING_DTYPE = "float32"


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    model_name: str
    device_mode: str
    openai_base_url: str
    openai_dimensions: int | None
    openai_max_input_tokens: int
    openai_max_batch_tokens: int
    openai_max_retries: int
    openai_retry_base_delay_sec: float
    normalize_embeddings: bool
    dtype: str
    cpu_workers: int


class EmbeddingBackend(Protocol):
    provider: str
    model_name: str
    device_mode: str | None

    def encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        ...

    def close(self) -> None:
        ...


def _normalize_provider(value: str | None) -> str:
    token = str(value or "").strip().lower().replace("-", "_")
    if token in {"", "sentence_transformers", "sentence_transformer", "sentence_transformers_cpu"}:
        return "sentence_transformers"
    if token in {"openai", "openai_api"}:
        return "openai"
    raise ValueError(f"Unsupported embedding provider: {value}")


def _resolve_device_mode() -> str:
    device_env = os.getenv("EMBED_DEVICE", "auto").strip().lower()
    if device_env == "auto":
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu_mp"
    return device_env


def load_embedding_settings() -> EmbeddingSettings:
    provider = _normalize_provider(os.getenv("EMBEDDING_PROVIDER", "sentence_transformers"))
    if provider == "openai":
        default_model = DEFAULT_OPENAI_EMBEDDING_MODEL
        device_mode = "remote_api"
    else:
        default_model = DEFAULT_SENTENCE_TRANSFORMER_MODEL
        device_mode = _resolve_device_mode()

    model_name = os.getenv("EMBEDDING_MODEL", default_model).strip() or default_model
    openai_dimensions_raw = os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "").strip()
    openai_dimensions = int(openai_dimensions_raw) if openai_dimensions_raw else None
    cpu_workers_raw = os.getenv("EMBED_CPU_WORKERS", "").strip()
    cpu_workers = int(cpu_workers_raw) if cpu_workers_raw else DEFAULT_CPU_WORKERS
    max_input_tokens_raw = os.getenv("OPENAI_MAX_INPUT_TOKENS", "").strip()
    max_batch_tokens_raw = os.getenv("OPENAI_MAX_BATCH_TOKENS", "").strip()
    max_retries_raw = os.getenv("OPENAI_MAX_RETRIES", "").strip()
    retry_delay_raw = os.getenv("OPENAI_RETRY_BASE_DELAY_SEC", "").strip()

    return EmbeddingSettings(
        provider=provider,
        model_name=model_name,
        device_mode=device_mode,
        openai_base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip("/"),
        openai_dimensions=openai_dimensions,
        openai_max_input_tokens=(
            int(max_input_tokens_raw) if max_input_tokens_raw else DEFAULT_OPENAI_MAX_INPUT_TOKENS
        ),
        openai_max_batch_tokens=(
            int(max_batch_tokens_raw) if max_batch_tokens_raw else DEFAULT_OPENAI_MAX_BATCH_TOKENS
        ),
        openai_max_retries=int(max_retries_raw) if max_retries_raw else DEFAULT_OPENAI_MAX_RETRIES,
        openai_retry_base_delay_sec=(
            float(retry_delay_raw) if retry_delay_raw else DEFAULT_OPENAI_RETRY_BASE_DELAY_SEC
        ),
        normalize_embeddings=NORMALIZE_EMBEDDINGS,
        dtype=EMBEDDING_DTYPE,
        cpu_workers=max(1, cpu_workers),
    )


class SentenceTransformerEmbeddingBackend:
    provider = "sentence_transformers"

    def __init__(self, settings: EmbeddingSettings):
        self.model_name = settings.model_name
        self.device_mode = settings.device_mode
        self._normalize_embeddings = settings.normalize_embeddings
        self._dtype = settings.dtype
        self._pool = None

        if self.device_mode == "mps":
            self._model = SentenceTransformer(self.model_name, device="mps")
        else:
            self._model = SentenceTransformer(self.model_name)
            self._pool = self._model.start_multi_process_pool(target_devices=["cpu"] * settings.cpu_workers)

    def encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        if self._pool is not None:
            return self._model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=True,
                convert_to_numpy=True,
                normalize_embeddings=self._normalize_embeddings,
                precision=self._dtype,
                pool=self._pool,
            ).astype(np.float32)

        return self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=self._normalize_embeddings,
            precision=self._dtype,
        ).astype(np.float32)

    def close(self) -> None:
        if self._pool is not None:
            self._model.stop_multi_process_pool(self._pool)
            self._pool = None


class OpenAIEmbeddingBackend:
    provider = "openai"

    def __init__(self, settings: EmbeddingSettings):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set")

        self.model_name = settings.model_name
        self.device_mode = settings.device_mode
        self._dimensions = settings.openai_dimensions
        self._max_input_tokens = settings.openai_max_input_tokens
        self._max_batch_tokens = settings.openai_max_batch_tokens
        self._max_retries = settings.openai_max_retries
        self._retry_base_delay_sec = settings.openai_retry_base_delay_sec
        self._normalize_embeddings = settings.normalize_embeddings
        try:
            self._encoding = tiktoken.encoding_for_model(self.model_name)
        except KeyError:
            self._encoding = tiktoken.get_encoding("cl100k_base")
        self._client = httpx.Client(
            base_url=settings.openai_base_url,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def _encode_token_count(self, text: str) -> int:
        return len(self._encoding.encode(text))

    def _truncate_text(self, text: str) -> str:
        token_ids = self._encoding.encode(text)
        if len(token_ids) <= self._max_input_tokens:
            return text
        return self._encoding.decode(token_ids[: self._max_input_tokens])

    def _prepare_texts(self, texts: list[str]) -> list[str]:
        return [self._truncate_text(str(text or "").strip()) for text in texts]

    def _iter_batches(self, texts: list[str], batch_size: int):
        batch: list[str] = []
        batch_tokens = 0

        for text in texts:
            token_count = self._encode_token_count(text)
            if batch and (len(batch) >= batch_size or batch_tokens + token_count > self._max_batch_tokens):
                yield batch
                batch = []
                batch_tokens = 0

            batch.append(text)
            batch_tokens += token_count

        if batch:
            yield batch

    def _is_retryable_status(self, status_code: int) -> bool:
        return status_code in {429, 500, 502, 503, 504}

    def _post_embeddings(self, payload: dict[str, object]) -> dict:
        for attempt in range(self._max_retries + 1):
            response = self._client.post("/embeddings", json=payload)
            try:
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                detail = response.text.strip()
                if not self._is_retryable_status(status_code) or attempt >= self._max_retries:
                    if detail:
                        raise RuntimeError(
                            f"OpenAI embeddings request failed with {status_code}: {detail}"
                        ) from exc
                    raise
                delay = self._retry_base_delay_sec * (2**attempt)
                time.sleep(delay)
        raise RuntimeError("OpenAI embeddings request retries exhausted")

    def encode(self, texts: list[str], batch_size: int) -> np.ndarray:
        vectors: list[list[float]] = []
        prepared_texts = self._prepare_texts(texts)
        for batch in self._iter_batches(prepared_texts, batch_size):
            payload: dict[str, object] = {
                "model": self.model_name,
                "input": batch,
            }
            if self._dimensions is not None:
                payload["dimensions"] = self._dimensions

            body = self._post_embeddings(payload)
            items = sorted(body.get("data", []), key=lambda item: int(item.get("index", 0)))
            vectors.extend(item["embedding"] for item in items)

        array = np.asarray(vectors, dtype=np.float32)
        if self._normalize_embeddings and len(array):
            norms = np.linalg.norm(array, axis=1, keepdims=True)
            norms[norms == 0.0] = 1.0
            array = array / norms
        return array.astype(np.float32)

    def close(self) -> None:
        self._client.close()


def create_embedding_backend(settings: EmbeddingSettings | None = None) -> EmbeddingBackend:
    resolved = settings or load_embedding_settings()
    if resolved.provider == "openai":
        return OpenAIEmbeddingBackend(resolved)
    return SentenceTransformerEmbeddingBackend(resolved)
