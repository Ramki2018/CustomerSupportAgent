"""Vector-store adapter for Qdrant."""

from __future__ import annotations

import atexit
import os
from functools import lru_cache
from dataclasses import dataclass
from typing import Any

from .. import config
from .embeddings import get_embedding_provider


class VectorStore:
    """Abstract storage wrapper so the retrieval backend can be swapped cleanly."""

    def upsert_documents(self, documents: list[dict]) -> None:
        raise NotImplementedError

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        raise NotImplementedError


@dataclass
class QdrantVectorStore(VectorStore):
    """Minimal Qdrant wrapper used by the ingestion pipeline."""

    collection_name: str
    vector_size: int
    url: str | None = None
    api_key: str | None = None
    prefer_grpc: bool = False

    def __post_init__(self) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as rest
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise ImportError(
                "qdrant-client is not installed. Install it to ingest into Qdrant."
            ) from exc

        self._rest = rest
        self._client = self._build_client(QdrantClient)
        # Close the client while the interpreter is still fully alive. Otherwise the client's
        # __del__ runs during shutdown and prints "ImportError: sys.meta_path is None".
        atexit.register(self.close)

    def close(self) -> None:
        """Close the underlying Qdrant client (safe to call more than once)."""
        client = getattr(self, "_client", None)
        if client is None:
            return
        self._client = None
        try:
            client.close()
        except Exception:
            pass

    def _build_client(self, qdrant_client_cls: Any):
        url = self.url or os.getenv("QDRANT_URL", "http://localhost:6333")
        api_key = self.api_key or os.getenv("QDRANT_API_KEY") or None
        local_path = config.QDRANT_LOCAL_PATH

        if url and url.startswith(("http://", "https://")):
            try:
                client = qdrant_client_cls(
                    url=url,
                    api_key=api_key,
                    prefer_grpc=self.prefer_grpc,
                )
                client.get_collections()
                return client
            except Exception:
                pass

        local_path.mkdir(parents=True, exist_ok=True)
        return qdrant_client_cls(
            path=str(local_path),
            prefer_grpc=self.prefer_grpc,
        )

    def ensure_collection(self) -> None:
        collections = self._client.get_collections().collections
        if any(collection.name == self.collection_name for collection in collections):
            return
        self._client.create_collection(
            collection_name=self.collection_name,
            vectors_config=self._rest.VectorParams(
                size=self.vector_size,
                distance=self._rest.Distance.COSINE,
            ),
        )

    def search(self, query: str, top_k: int = 5, *, embedding_provider: Any | None = None) -> list[dict]:
        try:
            self.ensure_collection()
        except Exception:
            return []

        provider = embedding_provider or get_embedding_provider()
        try:
            query_vector = provider.embed_query(query)
        except Exception:
            return []

        try:
            response = self._client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception:
            return []

        results: list[dict] = []
        for point in getattr(response, "points", []) or []:
            payload = point.payload or {}
            text = payload.get("text", "")
            if not text:
                continue
            source = payload.get("source") or str(point.id)
            results.append(
                {
                    "doc_id": source,
                    "chunk_id": str(point.id),
                    "text": text,
                    "score": float(point.score or 0.0),
                    "metadata": {
                        "source": source,
                        "chunk_id": str(point.id),
                        "page": payload.get("page"),
                        "section": payload.get("section"),
                        "policy_type": payload.get("policy_type"),
                        "retrieval_backend": "qdrant",
                    },
                }
            )
        return results

    def upsert_documents(self, documents: list[dict]) -> None:
        self.ensure_collection()
        points = []
        for document in documents:
            point_id = document["id"]
            vector = document["vector"]
            payload = document["payload"]
            points.append(
                self._rest.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )
        self._client.upsert(collection_name=self.collection_name, points=points)


@lru_cache(maxsize=1)
def get_default_vector_store() -> QdrantVectorStore:
    embedding_dim = len(get_embedding_provider().embed_query("dimension probe"))
    return QdrantVectorStore(
        collection_name=config.QDRANT_COLLECTION,
        vector_size=embedding_dim,
        url=config.QDRANT_URL,
        api_key=config.QDRANT_API_KEY or None,
    )
