"""
Qdrant Store — thin wrapper around qdrant-client for vector operations.

Handles:
  - Collection initialization (creates if not exists)
  - Upserting text + metadata with vector embeddings
  - Semantic search
  - Health checks
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
)

from packages.shared.config import settings

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────
VECTOR_DIM = 768  # nomic-embed-text default dimension
COLLECTION = settings.qdrant_collection

# ── Lazy client (created on first use) ───────────────────────────────
_client: QdrantClient | None = None


def _qdrant_client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if (settings.qdrant_url or "").strip():
        kwargs["url"] = settings.qdrant_url.strip()
    else:
        kwargs["host"] = settings.qdrant_host
        kwargs["port"] = settings.qdrant_port
    if (settings.qdrant_api_key or "").strip():
        kwargs["api_key"] = settings.qdrant_api_key.strip()
    return kwargs


def _get_client() -> QdrantClient:
    """Get or create the Qdrant client singleton."""
    global _client
    if _client is None:
        _client = QdrantClient(**_qdrant_client_kwargs())
    return _client


async def init_collections() -> None:
    """Create the default collection if it doesn't exist."""
    client = _get_client()
    collections = await asyncio.to_thread(client.get_collections)
    collections = collections.collections
    existing = {c.name for c in collections}

    if COLLECTION not in existing:
        await asyncio.to_thread(
            client.create_collection,
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection: %s", COLLECTION)
    else:
        logger.info("Qdrant collection already exists: %s", COLLECTION)


async def health_check() -> list[str]:
    """Return list of existing collection names (proves connectivity)."""
    client = _get_client()
    collections = await asyncio.to_thread(client.get_collections)
    collections = collections.collections
    return [c.name for c in collections]


async def export_snapshot(collection_name: str | None = None) -> dict[str, str]:
    """
    Create a Qdrant collection snapshot.

    Args:
        collection_name: Optional collection override.

    Returns:
        Snapshot metadata with collection and snapshot name.
    """
    client = _get_client()
    target_collection = collection_name or COLLECTION

    snapshot = await asyncio.to_thread(
        client.create_snapshot,
        collection_name=target_collection,
    )

    snapshot_name = ""
    if isinstance(snapshot, dict):
        snapshot_name = str(snapshot.get("name", ""))
    else:
        snapshot_name = str(getattr(snapshot, "name", ""))

    logger.info(
        "Created snapshot for collection %s: %s",
        target_collection,
        snapshot_name or "<unknown>",
    )

    return {
        "collection": target_collection,
        "snapshot": snapshot_name,
    }


async def upsert(
    text: str,
    metadata: dict[str, Any],
    point_id: str | None = None,
) -> str:
    """
    Embed text and upsert into Qdrant.

    Args:
        text:     The content to embed and store.
        metadata: Arbitrary metadata attached to the point.
        point_id: Optional deterministic ID; auto-generated if None.

    Returns:
        The point ID used.
    """
    client = _get_client()
    embedding = await _embed(text)

    if point_id is None:
        # Deterministic ID from content + source metadata to avoid collisions
        source = metadata.get("source_path", "")
        chunk_idx = metadata.get("chunk_index", "")
        seed = f"{source}::{chunk_idx}\n{text}" if source else text
        point_id = hashlib.sha256(seed.encode()).hexdigest()[:32]

    # Store the original text in metadata for retrieval
    metadata["_content"] = text

    await asyncio.to_thread(
        client.upsert,
        collection_name=COLLECTION,
        points=[
            PointStruct(
                id=point_id,
                vector=embedding,
                payload=metadata,
            )
        ],
    )
    logger.info("Upserted point %s into %s", point_id, COLLECTION)
    return point_id


async def search(
    query: str,
    k: int = 5,
    filter_conditions: dict | None = None,
) -> list[dict[str, Any]]:
    """
    Semantic search: embed query then find nearest neighbors.

    Returns:
        List of dicts with keys: id, score, content, metadata
    """
    client = _get_client()
    query_vector = await _embed(query)

    query_filter = _build_filter(filter_conditions)
    results = await asyncio.to_thread(
        client.query_points,
        collection_name=COLLECTION,
        query=query_vector,
        limit=k,
        query_filter=query_filter,
    )
    results = results.points

    return [
        {
            "id": str(hit.id),
            "score": hit.score,
            "content": hit.payload.get("_content", ""),
            "metadata": {k: v for k, v in hit.payload.items() if k != "_content"},
        }
        for hit in results
    ]


def _build_filter(filter_conditions: dict | None) -> Filter | None:
    """Build a Qdrant filter from a simple dict of conditions."""
    if not filter_conditions:
        return None

    must: list[FieldCondition] = []
    for key, value in filter_conditions.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            values = [v for v in value if v is not None]
            if values:
                must.append(FieldCondition(key=key, match=MatchAny(any=values)))
        else:
            must.append(FieldCondition(key=key, match=MatchValue(value=value)))

    return Filter(must=must) if must else None


# ── Embedding via Ollama ─────────────────────────────────────────────

async def _embed(text: str) -> list[float]:
    """
    Get embedding vector from Ollama's embedding endpoint.
    Uses the model configured in settings.embedding_model.
    """
    url = f"{settings.ollama_api_base}/api/embed"
    payload = {
        "model": settings.embedding_model,
        "input": text,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    embeddings = data.get("embeddings", [])
    if not embeddings:
        raise ValueError(f"No embeddings returned for text: {text[:50]}…")

    return embeddings[0]
