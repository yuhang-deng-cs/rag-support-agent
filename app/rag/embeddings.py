"""Embedding providers behind one async interface."""

from __future__ import annotations

import asyncio
import hashlib
import math
from typing import Protocol

import httpx

from app.core.config import Settings
from app.rag.text import terms


class Embedder(Protocol):
    dim: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


class HashingEmbedder:
    """Deterministic lexical embedding via signed feature hashing.

    Not semantic - it only matches shared words/bigrams. It exists so tests and CI run
    offline in milliseconds. Use `fastembed` or an API model for real retrieval quality.
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for term in terms(text):
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            vec[value % self.dim] += 1.0 if (value >> 63) & 1 else -1.0
        return _l2_normalize(vec)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FastEmbedEmbedder:
    """Local ONNX embeddings via `fastembed` (downloads the model once, no API key)."""

    def __init__(self, model_name: str, dim: int) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                'EMBEDDING_PROVIDER=fastembed requires: pip install ".[local]"'
            ) from exc
        self._model = TextEmbedding(model_name=model_name)
        self.dim = dim

    def _run(self, texts: list[str]) -> list[list[float]]:
        vectors = [v.tolist() for v in self._model.embed(texts)]
        if vectors and len(vectors[0]) != self.dim:
            raise RuntimeError(
                f"Model produced {len(vectors[0])}-dim vectors but EMBEDDING_DIM={self.dim}"
            )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._run, texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await asyncio.to_thread(self._run, [text]))[0]


class OpenAICompatibleEmbedder:
    """Any server implementing POST /embeddings (OpenAI, Azure, Ollama, vLLM, LiteLLM, ...)."""

    def __init__(
        self, base_url: str, api_key: str, model: str, dim: int, batch_size: int = 64
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=60.0,
        )
        self._model = model
        self._batch_size = batch_size
        self.dim = dim

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            resp = await self._client.post(
                "/embeddings", json={"model": self._model, "input": batch}
            )
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        if out and len(out[0]) != self.dim:
            raise RuntimeError(f"Model produced {len(out[0])}-dim vectors, expected {self.dim}")
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


def build_embedder(settings: Settings) -> Embedder:
    match settings.embedding_provider:
        case "hash":
            return HashingEmbedder(settings.embedding_dim)
        case "fastembed":
            return FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim)
        case "openai":
            return OpenAICompatibleEmbedder(
                settings.embedding_base_url,
                settings.embedding_api_key,
                settings.embedding_model,
                settings.embedding_dim,
            )
    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
