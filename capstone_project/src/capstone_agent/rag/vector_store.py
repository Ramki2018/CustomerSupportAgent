"""Vector-store adapter for Qdrant."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .. import config


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

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        raise NotImplementedError(
            "Search is not used by the ingestion script. Implement query-side retrieval separately."
        )
