"""
Memory Service — high-level API for storing and querying memories.

Sits on top of both qdrant_store (document RAG) AND mem0_client
(user-centric intelligent memory) to provide:
  - store_memory()              → embed + persist to Qdrant
  - query_memories()            → semantic search over Qdrant
  - build_context()             → hybrid assembly (Qdrant docs + Mem0 facts)
  - extract_and_store_from_turn → auto-learn from conversation via Mem0
  - get_all_user_memories()     → transparent view into Mem0 memories
  - forget_memory()             → delete a specific Mem0 memory
"""

from __future__ import annotations

import logging
from typing import Any

from packages.memory.schemas import MemoryItem, MemorySearchResult, MemoryType
from packages.memory import qdrant_store

logger = logging.getLogger(__name__)

# Ensure collections exist on first import
_initialized = False


async def _ensure_init() -> None:
    global _initialized
    if not _initialized:
        try:
            await qdrant_store.init_collections()
            _initialized = True
        except Exception as exc:
            logger.warning("Could not initialize Qdrant collections: %s", exc)
            raise


# ── Qdrant-based Memory (Document RAG) ──────────────────────────────


async def store_memory(
    user_id: str,
    content: str,
    memory_type: str = "PROFILE",
) -> dict[str, Any]:
    """
    Store a new memory in Qdrant.

    Returns:
        Dict with 'id' and 'memory_type' of the stored item.
    """
    await _ensure_init()

    item = MemoryItem(
        user_id=user_id,
        content=content,
        memory_type=MemoryType(memory_type),
    )

    metadata = {
        "user_id": item.user_id,
        "memory_type": item.memory_type.value,
        "timestamp": item.timestamp.isoformat(),
    }

    point_id = await qdrant_store.upsert(
        text=item.content,
        metadata=metadata,
        point_id=item.id,
    )

    logger.info("Stored memory %s (type=%s) for user %s", point_id, memory_type, user_id)
    return {"id": point_id, "memory_type": memory_type}


async def query_memories(
    user_id: str,
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Semantic search for memories related to a query.

    Returns:
        List of MemorySearchResult-like dicts sorted by relevance.
    """
    await _ensure_init()

    raw_results = await qdrant_store.search(query=query, k=k)

    # Filter by user_id and map to response format
    results = []
    for hit in raw_results:
        meta = hit.get("metadata", {})
        if meta.get("user_id", "default") == user_id:
            results.append(
                MemorySearchResult(
                    id=hit["id"],
                    content=hit["content"],
                    memory_type=meta.get("memory_type", "PROFILE"),
                    score=hit["score"],
                    metadata=meta,
                ).model_dump()
            )

    return results


# ── Mem0-based Memory (User-Centric Intelligence) ───────────────────


async def extract_and_store_from_turn(
    messages: list[dict[str, str]],
    user_id: str = "default",
) -> dict[str, Any]:
    """
    Auto-extract facts from a conversation turn via Mem0.

    Mem0 internally decides what's worth remembering:
    - Deduplicates against existing memories
    - Merges conflicting facts
    - Categorizes automatically

    Args:
        messages: The conversation exchange (user + assistant).
        user_id:  Owner of these memories.

    Returns:
        Extraction result from Mem0 (new memories added/updated).
    """
    try:
        from packages.memory.mem0_client import mem0_add
        result = mem0_add(messages, user_id=user_id)
        logger.info(
            "Extracted memories from turn for user=%s: %s",
            user_id, result,
        )
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        logger.warning("Mem0 extraction failed (non-fatal): %s", exc)
        return {"error": str(exc), "extracted": 0}


async def get_all_user_memories(
    user_id: str = "default",
) -> list[dict[str, Any]]:
    """
    Get all Mem0 memories for a user (for transparency & debugging).

    Returns:
        List of all stored Mem0 memory dicts.
    """
    try:
        from packages.memory.mem0_client import mem0_get_all
        return mem0_get_all(user_id=user_id)
    except Exception as exc:
        logger.warning("Could not retrieve Mem0 memories: %s", exc)
        return []


async def forget_memory(memory_id: str) -> dict[str, Any]:
    """
    Delete a specific Mem0 memory by ID.

    Returns:
        Deletion result.
    """
    try:
        from packages.memory.mem0_client import mem0_delete
        result = mem0_delete(memory_id)
        return {"status": "deleted", "memory_id": memory_id, "result": result}
    except Exception as exc:
        logger.error("Failed to delete memory %s: %s", memory_id, exc)
        return {"status": "error", "error": str(exc)}


# ── Hybrid Context Assembly ──────────────────────────────────────────


async def build_context(
    user_message: str,
    user_id: str = "default",
    k: int = 5,
) -> str:
    """
    Build a hybrid context string from both Qdrant RAG and Mem0 memories.

    Combines:
      1. User profile & preference facts from Mem0
      2. Relevant document/code chunks from Qdrant

    Returns:
        A system-prompt-style string, or empty string if nothing found.
    """
    sections = []

    # ── Section 1: Mem0 user memories (preferences, facts) ───────
    try:
        from packages.memory.mem0_client import mem0_search
        mem0_results = mem0_search(user_message, user_id=user_id, limit=k)
        if mem0_results:
            lines = ["## What I Know About You\n"]
            for i, mem in enumerate(mem0_results, 1):
                memory_text = mem.get("memory", mem.get("content", ""))
                if memory_text:
                    lines.append(f"  {i}. {memory_text}")
            sections.append("\n".join(lines))
    except Exception as exc:
        logger.debug("Mem0 context unavailable: %s", exc)

    # ── Section 2: Qdrant document/code RAG ──────────────────────
    try:
        qdrant_results = await qdrant_store.search(query=user_message, k=k)
        # Filter for document content (not user memories stored directly)
        doc_results = [
            r for r in qdrant_results
            if r.get("metadata", {}).get("content_type") == "document"
            or r.get("metadata", {}).get("source_path")
        ]
        if doc_results:
            lines = ["## Relevant Documents & Code\n"]
            for i, hit in enumerate(doc_results, 1):
                meta = hit.get("metadata", {})
                source = meta.get("source_path", "unknown")
                section = meta.get("section", meta.get("section_title", ""))
                content = hit["content"][:500]  # Truncate for context window
                label = f"{source}"
                if section:
                    label += f" → {section}"
                lines.append(f"  {i}. [{label}]\n     {content}")
            sections.append("\n".join(lines))
    except Exception as exc:
        logger.debug("Qdrant context unavailable: %s", exc)

    # ── Section 3: Direct Qdrant user memories (legacy) ──────────
    try:
        legacy_results = await query_memories(
            user_id=user_id, query=user_message, k=3,
        )
        # Only include legacy memories not already covered by Mem0
        if legacy_results and not sections:
            lines = ["## Previous Interactions\n"]
            for i, mem in enumerate(legacy_results, 1):
                lines.append(
                    f"  {i}. [{mem['memory_type']}] {mem['content']}"
                )
            sections.append("\n".join(lines))
    except Exception as exc:
        logger.debug("Legacy memory context unavailable: %s", exc)

    if not sections:
        return ""

    # Assemble final context
    header = (
        "Use the following context to personalize your response. "
        "Reference specific facts when relevant, but don't repeat "
        "them verbatim unless asked.\n\n"
    )
    return header + "\n\n".join(sections)
