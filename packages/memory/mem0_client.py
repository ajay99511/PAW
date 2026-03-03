"""
Mem0 Client — intelligent memory layer backed by Qdrant + Ollama.

Provides automatic fact extraction, deduplication, and consolidation
using Mem0's Memory class. Fully local: uses Ollama for both LLM
inference (fact extraction) and embeddings.

Usage:
    from packages.memory.mem0_client import mem0_add, mem0_search, mem0_get_all

    # Auto-extract facts from a conversation
    result = mem0_add(messages, user_id="default")

    # Search memories
    results = mem0_search("What does the user prefer?", user_id="default")
"""

from __future__ import annotations

import logging
from typing import Any

from packages.shared.config import settings

logger = logging.getLogger(__name__)

# ── Lazy singleton ───────────────────────────────────────────────────

_memory_instance = None
_init_attempted = False


def _get_mem0():
    """Get or create the Mem0 Memory singleton."""
    global _memory_instance, _init_attempted

    if _memory_instance is not None:
        return _memory_instance

    if _init_attempted:
        raise RuntimeError("Mem0 initialization previously failed. Restart to retry.")

    _init_attempted = True

    try:
        from mem0 import Memory
    except ImportError:
        raise ImportError(
            "mem0ai is required. Install with: pip install mem0ai"
        )

    config = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": getattr(settings, "mem0_collection", "mem0_memories"),
                "host": settings.qdrant_host,
                "port": settings.qdrant_port,
                "embedding_model_dims": 768,  # nomic-embed-text dimension
            },
        },
        "llm": {
            "provider": "ollama",
            "config": {
                "model": settings.default_local_model.replace("ollama/", ""),
                "temperature": 0,
                "max_tokens": 2000,
                "ollama_base_url": settings.ollama_api_base,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": settings.embedding_model,
                "ollama_base_url": settings.ollama_api_base,
            },
        },
    }

    logger.info("Initializing Mem0 with config: vector_store=qdrant, llm=ollama, embedder=ollama")
    _memory_instance = Memory.from_config(config)
    logger.info("Mem0 initialized successfully")

    return _memory_instance


# ── Public API ───────────────────────────────────────────────────────


def mem0_add(
    messages: list[dict[str, str]] | str,
    user_id: str = "default",
    agent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Add memories from a conversation or plain text.

    Mem0 internally extracts salient facts, deduplicates against
    existing memories, and stores only what's new or updated.

    Args:
        messages: Either a list of {"role": ..., "content": ...} dicts
                  or a plain string.
        user_id:  Owner of these memories.
        agent_id: Optional agent identifier.
        metadata: Optional extra metadata to attach.

    Returns:
        Dict with extraction results from Mem0.
    """
    m = _get_mem0()

    kwargs: dict[str, Any] = {"user_id": user_id}
    if agent_id:
        kwargs["agent_id"] = agent_id
    if metadata:
        kwargs["metadata"] = metadata

    result = m.add(messages, **kwargs)
    logger.info("Mem0 add for user=%s: %s", user_id, result)
    return result


def mem0_search(
    query: str,
    user_id: str = "default",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Search memories by semantic similarity.

    Args:
        query:   Natural language query.
        user_id: Filter by user.
        limit:   Max results.

    Returns:
        List of memory dicts with id, memory, score, etc.
    """
    m = _get_mem0()
    results = m.search(query, user_id=user_id, limit=limit)

    # Normalize response format
    if isinstance(results, dict) and "results" in results:
        return results["results"]
    elif isinstance(results, list):
        return results
    else:
        return []


def mem0_get_all(user_id: str = "default") -> list[dict[str, Any]]:
    """
    Retrieve all memories for a user.

    Returns:
        List of all stored memory dicts.
    """
    m = _get_mem0()
    results = m.get_all(user_id=user_id)

    # Normalize response format
    if isinstance(results, dict) and "results" in results:
        return results["results"]
    elif isinstance(results, list):
        return results
    else:
        return []


def mem0_update(memory_id: str, data: str) -> dict[str, Any]:
    """
    Update a specific memory by ID.

    Args:
        memory_id: The memory to update.
        data:      New content for the memory.

    Returns:
        Update result from Mem0.
    """
    m = _get_mem0()
    result = m.update(memory_id, data)
    logger.info("Mem0 update memory_id=%s", memory_id)
    return result


def mem0_delete(memory_id: str) -> dict[str, Any]:
    """
    Delete a specific memory by ID.

    Args:
        memory_id: The memory to delete.

    Returns:
        Deletion result from Mem0.
    """
    m = _get_mem0()
    result = m.delete(memory_id)
    logger.info("Mem0 deleted memory_id=%s", memory_id)
    return result
