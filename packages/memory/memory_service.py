"""
Memory Service - 5-Layer Memory System Integration

Sits on top of qdrant_store (document RAG) and the local memory extractor
(user-centric long-term memory) to provide:
  - store_memory()              -> embed + persist to Qdrant
  - query_memories()            -> semantic search over Qdrant
  - build_context()             -> HYBRID assembly (local facts + 5-Layer context)
  - extract_and_store_from_turn -> auto-learn from conversation via local memory extraction
  - get_all_user_memories()     -> transparent view into stored memories
  - forget_memory()             -> delete a specific memory
  - compact_session_if_needed() -> Layer 4 compaction trigger

5-Layer Memory Architecture:
  Layer 1: Bootstrap Injection (AGENTS.md, SOUL.md, USER.md, etc.)
  Layer 2: JSONL Transcripts (append-only session history)
  Layer 3: Session Pruning (in-memory, TTL-aware)
  Layer 4: Compaction (adaptive summarization)
  Layer 5: Long-Term Memory Search (local memory + Qdrant hybrid)

Usage:
    from packages.memory.memory_service import build_context, compact_session_if_needed
    
    # Build hybrid context (local memory + 5-Layer)
    context = await build_context(user_message, user_id="default")
    
    # Check if compaction needed
    await compact_session_if_needed(session_id)
"""

from __future__ import annotations

import logging
from typing import Any
import asyncio

from packages.memory import qdrant_store
from packages.memory.schemas import MemoryItem, MemorySearchResult, MemoryType
from packages.shared.config import settings
from packages.shared.redaction import redact_text

logger = logging.getLogger(__name__)

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


def _clip_text(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _fit_section(sections: list[str], candidate: str, budget: int) -> bool:
    if not candidate.strip():
        return False

    current = "\n\n".join(sections)
    remaining = budget - len(current)
    if remaining <= 0:
        return False

    if sections:
        remaining -= 2
    if remaining <= 0:
        return False

    clipped = _clip_text(candidate, remaining)
    if not clipped.strip():
        return False

    sections.append(clipped)
    return True


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
        "content_type": "memory",
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

    raw_results = await qdrant_store.search(
        query=query,
        k=k,
        filter_conditions={"content_type": "memory", "user_id": user_id},
    )

    results = []
    for hit in raw_results:
        meta = hit.get("metadata", {})
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


async def extract_and_store_from_turn(
    messages: list[dict[str, str]],
    user_id: str = "default",
) -> dict[str, Any]:
    """
    Auto-extract facts from a conversation turn via local memory extraction.
    """
    try:
        from packages.memory.mem0_client import mem0_add

        result = await asyncio.to_thread(mem0_add, messages, user_id=user_id)
        logger.info(
            "Extracted memories from turn for user=%s: %s",
            user_id,
            result,
        )
        return result if isinstance(result, dict) else {"result": result}
    except Exception as exc:
        logger.warning("Local memory extraction failed (non-fatal): %s", exc)
        return {"error": str(exc), "extracted": 0}


async def get_all_user_memories(
    user_id: str = "default",
) -> list[dict[str, Any]]:
    """
    Get all stored memories for a user (for transparency and debugging).
    """
    try:
        from packages.memory.mem0_client import mem0_get_all

        return await asyncio.to_thread(mem0_get_all, user_id=user_id)
    except Exception as exc:
        logger.warning("Could not retrieve stored memories: %s", exc)
        return []


async def forget_memory(memory_id: str) -> dict[str, Any]:
    """
    Delete a specific memory by ID.
    """
    try:
        from packages.memory.mem0_client import mem0_delete

        result = await asyncio.to_thread(mem0_delete, memory_id)
        return {"status": "deleted", "memory_id": memory_id, "result": result}
    except Exception as exc:
        logger.error("Failed to delete memory %s: %s", memory_id, exc)
        return {"status": "error", "error": str(exc)}


async def build_context(
    user_message: str,
    user_id: str = "default",
    k: int = 5,
) -> str:
    """
    Build a compact hybrid context string from:
    - Layer 1: Bootstrap files (AGENTS.md, SOUL.md, USER.md, etc.)
    - Layer 2-4: Recent session context (JSONL transcripts, pruned)
    - Layer 5: local facts + Qdrant documents
    
    Args:
        user_message: Current user message
        user_id: User identifier
        k: Number of results to fetch from vector search
    
    Returns:
        Formatted context string, or empty string if no context available
    """
    total_budget = max(settings.rag_context_char_budget, 400)
    sections: list[str] = []
    
    # === LAYER 1: Bootstrap Injection ===
    try:
        from packages.memory.bootstrap import load_bootstrap_files
        
        bootstrap_context = await load_bootstrap_files(agent_type="main")
        if bootstrap_context:
            # Redact any secrets in bootstrap context
            bootstrap_context, _ = redact_text(bootstrap_context)
            _fit_section(
                sections,
                "## Project Context (Bootstrap)\n" + bootstrap_context,
                total_budget,
            )
            logger.debug("Layer 1 (Bootstrap): context loaded")
    except Exception as exc:
        logger.debug("Layer 1 (Bootstrap) unavailable: %s", exc)
    
    # === LAYER 5A: Local Facts (User-Centric Memory) ===
    try:
        from packages.memory.mem0_client import mem0_search

        memory_results = await asyncio.to_thread(
            mem0_search,
            user_message,
            user_id=user_id,
            limit=min(k, settings.rag_memory_limit),
        )
        memory_lines = []
        for i, mem in enumerate(memory_results[: settings.rag_memory_limit], 1):
            memory_text = mem.get("memory", mem.get("content", ""))
            # Redact secrets
            memory_text, _ = redact_text(memory_text)
            clipped = _clip_text(memory_text, 220)
            if clipped:
                memory_lines.append(f"  {i}. {clipped}")
        if memory_lines:
            _fit_section(
                sections,
                "## What I Know About You (Long-Term Facts)\n" + "\n".join(memory_lines),
                total_budget,
            )
            logger.debug("Layer 5A (Local): %d facts loaded", len(memory_lines))
    except Exception as exc:
        logger.debug("Layer 5A (Local) unavailable: %s", exc)

    # === LAYER 5B: Qdrant Documents (RAG) ===
    try:
        qdrant_results = await qdrant_store.search(
            query=user_message,
            k=k,
            filter_conditions={"content_type": "document"},
        )
        doc_results = [
            r for r in qdrant_results
            if r.get("metadata", {}).get("content_type") == "document"
            or r.get("metadata", {}).get("source")
            or r.get("metadata", {}).get("source_path")
        ]
        doc_lines = []
        for i, hit in enumerate(doc_results[:3], 1):
            meta = hit.get("metadata", {})
            source = meta.get("source") or meta.get("source_path") or "unknown"
            section = meta.get("section", meta.get("section_title", ""))
            content = _clip_text(hit.get("content", ""), settings.rag_doc_snippet_chars)
            # Redact secrets
            content, _ = redact_text(content)
            if not content:
                continue
            label = source
            if section:
                label += f" -> {section}"
            doc_lines.append(f"  {i}. [{label}] {content}")
        if doc_lines:
            _fit_section(
                sections,
                "## Relevant Documents and Code\n" + "\n".join(doc_lines),
                total_budget,
            )
            logger.debug("Layer 5B (Qdrant): %d documents loaded", len(doc_lines))
    except Exception as exc:
        logger.debug("Layer 5B (Qdrant) unavailable: %s", exc)

    # === LAYER 2-4: Session Context (Recent Conversation) ===
    # This would be populated from JSONL transcripts if session_id is provided
    # For now, we rely on the calling code to pass session context via messages
    
    # Fallback to legacy memory search if nothing found
    if not sections:
        try:
            from packages.memory.qdrant_store import search as qdrant_search
            
            legacy_results = await qdrant_search(
                query=user_message,
                k=3,
                filter_conditions={"content_type": "memory"},
            )
            legacy_lines = []
            for i, mem in enumerate(legacy_results[:3], 1):
                clipped = _clip_text(mem.get("content", ""), 220)
                if clipped:
                    memory_type = mem.get("metadata", {}).get("memory_type", "PROFILE")
                    legacy_lines.append(f"  {i}. [{memory_type}] {clipped}")
            if legacy_lines:
                _fit_section(
                    sections,
                    "## Previous Interactions\n" + "\n".join(legacy_lines),
                    total_budget,
                )
                logger.debug("Fallback (Legacy): %d memories loaded", len(legacy_lines))
        except Exception as exc:
            logger.debug("Fallback (Legacy) unavailable: %s", exc)

    if not sections:
        return ""

    header = (
        "Use this context to personalize the response. "
        "Reference relevant facts briefly and only when they materially help. "
        "When you use document content, cite the source path in brackets like [C:\\path\\file.ext]."
    )
    context = _clip_text(header + "\n\n" + "\n\n".join(sections), total_budget)
    
    logger.info("Built hybrid context: %d sections, %d chars", len(sections), len(context))
    return context


async def compact_session_if_needed(
    session_id: str,
    model: str = "local",
) -> bool:
    """
    Check if session needs compaction and trigger it if so.
    
    This is Layer 4 of the 5-layer memory system.
    
    Args:
        session_id: Session to check
        model: Model to use for summarization
    
    Returns:
        True if compaction was triggered
    """
    try:
        from packages.memory.compaction import should_compact, compact_session
        
        if await should_compact(session_id):
            logger.info(f"Compaction triggered for session {session_id}")
            result = await compact_session(session_id, model)
            
            if not result.skipped:
                logger.info(
                    f"Compaction completed: {result.entries_removed} entries removed, "
                    f"{result.tokens_before} → {result.tokens_after} tokens"
                )
                return True
        
        return False
    
    except Exception as exc:
        logger.warning(f"Compaction check failed: {exc}")
        return False
