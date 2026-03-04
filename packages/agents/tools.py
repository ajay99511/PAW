"""
Agent Tools — callable tool functions for the agent orchestrator.

These wrap existing memory/document search capabilities into
standalone async functions that agents can invoke during execution.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def search_user_memories(
    query: str,
    user_id: str = "default",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Search Mem0 for user-related facts and preferences.

    Returns list of memory dicts with 'memory', 'id', 'score' fields.
    """
    try:
        from packages.memory.mem0_client import mem0_search
        results = mem0_search(query, user_id=user_id, limit=limit)
        return results
    except Exception as exc:
        logger.warning("Memory search failed: %s", exc)
        return []


async def search_documents(
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Search Qdrant for ingested document/code chunks.

    Returns list of dicts with 'content', 'metadata', 'score' fields.
    """
    try:
        from packages.memory.qdrant_store import search
        results = await search(query=query, k=k)
        # Filter for document content only
        return [
            r for r in results
            if r.get("metadata", {}).get("content_type") == "document"
            or r.get("metadata", {}).get("source_path")
        ]
    except Exception as exc:
        logger.warning("Document search failed: %s", exc)
        return []


async def format_tool_results(
    memories: list[dict],
    documents: list[dict],
) -> str:
    """Format tool results into a context string for the next agent."""
    parts = []

    if memories:
        lines = ["### User Memories"]
        for i, m in enumerate(memories, 1):
            text = m.get("memory", m.get("content", ""))
            if text:
                lines.append(f"  {i}. {text}")
        parts.append("\n".join(lines))

    if documents:
        lines = ["### Relevant Documents"]
        for i, d in enumerate(documents, 1):
            source = d.get("metadata", {}).get("source_path", "unknown")
            content = d.get("content", "")[:300]
            lines.append(f"  {i}. [{source}] {content}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts) if parts else "No relevant context found."
