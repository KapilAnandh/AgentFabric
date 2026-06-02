from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient as BaseQdrantClient
from qdrant_client.http import models

from ..config_loader import get_config


class QdrantClient:
    DEFAULT_COLLECTION = "arp_knowledge"

    def __init__(self) -> None:
        config = get_config()
        qdrant_url = config["memory"]["qdrant_url"]
        self._client = BaseQdrantClient(url=qdrant_url)

    def ensure_collection(self, name: str = DEFAULT_COLLECTION, vector_size: int = 768) -> None:
        collections = self._client.get_collections().collections
        collection_names = {collection.name for collection in collections}
        if name not in collection_names:
            self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )

    def upsert(
        self,
        collection: str = DEFAULT_COLLECTION,
        id: str | int | None = None,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if id is None:
            raise ValueError("id is required")
        if vector is None:
            raise ValueError("vector is required")

        self._client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(
                    id=id,
                    vector=vector,
                    payload=payload or {},
                )
            ],
        )

    def search(
        self,
        collection: str = DEFAULT_COLLECTION,
        vector: list[float] | None = None,
        limit: int = 5,
    ):
        if vector is None:
            raise ValueError("vector is required")

        return self._client.search(
            collection_name=collection,
            query_vector=vector,
            limit=limit,
        )

    def delete(self, collection: str = DEFAULT_COLLECTION, id: str | int | None = None) -> None:
        if id is None:
            raise ValueError("id is required")

        self._client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=[id]),
        )
