"""Embedding adapter for the knowledge-base ingestion and retrieval pipeline.

The implementation prefers a sentence-transformers backend when available and
falls back to a deterministic hashing encoder for offline/demo environments.
That keeps the ingestion path usable even before heavyweight model downloads
are configured.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter

class EmbeddingProvider:
    """Thin abstraction over whichever embedding backend is selected."""

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic fallback embedding backend for offline demos."""

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9]+", text.lower())

    def _encode(self, text: str) -> list[float]:
        counts = Counter(self._tokenize(text))
        vector = [0.0] * self.dimensions
        for token, weight in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += float(weight)
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._encode(text) for text in texts]


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Sentence-transformers backend with a configurable model name."""

    def __init__(self, model_name: str | None = None):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise ImportError(
                "sentence-transformers is not installed. Install it or use the "
                "HashingEmbeddingProvider fallback."
            ) from exc

        self.model_name = model_name or os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        self._model = SentenceTransformer(self.model_name)

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode(text, normalize_embeddings=True).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, normalize_embeddings=True).tolist()


def get_embedding_provider() -> EmbeddingProvider:
    """Return the best available embedding backend for this environment."""
    preferred = os.getenv("EMBEDDING_BACKEND", "sentence_transformers").lower()
    if preferred in {"sentence_transformers", "bge-m3", "bgem3"}:
        try:
            model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
            return SentenceTransformerEmbeddingProvider(model_name=model_name)
        except Exception:
            # Keep the pipeline usable in lightweight environments.
            return HashingEmbeddingProvider()
    return HashingEmbeddingProvider()
