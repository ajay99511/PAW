"""
Memory Consolidation — periodic review and deduplication of local memories.

After N conversation turns, the system auto-reviews all stored memories
and asks the LLM to consolidate them: merge duplicates, flag stale facts,
and produce a cleaner set.

Usage:
    from packages.memory.consolidation import consolidate_memories, should_consolidate

    if should_consolidate(turn_count):
        result = await consolidate_memories(user_id="default")
"""

from __future__ import annotations

import logging
from typing import Any
import asyncio

from packages.shared.config import settings

logger = logging.getLogger(__name__)

# ── Turn counter (in-memory, resets on restart) ──────────────────────

_turn_counts: dict[str, int] = {}


def increment_turn(user_id: str = "default") -> int:
    """Increment and return the turn count for a user."""
    _turn_counts[user_id] = _turn_counts.get(user_id, 0) + 1
    return _turn_counts[user_id]


def get_turn_count(user_id: str = "default") -> int:
    """Get the current turn count for a user."""
    return _turn_counts.get(user_id, 0)


def reset_turn_count(user_id: str = "default") -> None:
    """Reset the turn count after consolidation."""
    _turn_counts[user_id] = 0


def should_consolidate(
    user_id: str = "default",
    threshold: int | None = None,
) -> bool:
    """
    Check if it's time to consolidate memories.

    Returns True every N turns (configurable via settings or override).
    """
    t = threshold or settings.consolidation_threshold
    count = get_turn_count(user_id)
    return count > 0 and count % t == 0


# ── Consolidation Logic ─────────────────────────────────────────────

CONSOLIDATION_PROMPT = """You are a memory management assistant. Review the following list of stored user memories and produce a consolidated version.

## Instructions:
1. **Merge duplicates**: If two memories say the same thing differently, keep one clear version.
2. **Resolve contradictions**: If memories conflict, keep the most recent or most specific one.
3. **Remove trivial facts**: Drop memories that are too vague to be useful.
4. **Preserve important facts**: Keep user preferences, project details, and key decisions.

## Current Memories:
{memories}

## Output Format:
For each memory you want to keep, output one line in this exact format:
KEEP: <memory text>

For each memory you want to remove (duplicate/stale/trivial), output:
REMOVE: <original memory text> | REASON: <brief reason>

For each memory pair you want to merge, output:
MERGE: <new merged memory text> | FROM: <original memory ids>
"""


async def consolidate_memories(
    user_id: str = "default",
    model: str = "local",
) -> dict[str, Any]:
    """
    Review and consolidate all local memories for a user.

    Uses the LLM to identify duplicates, resolve contradictions,
    and produce a cleaner memory set.

    Returns:
        Dict with consolidation results: kept, removed, merged counts.
    """
    from packages.memory.mem0_client import mem0_get_all, mem0_add, mem0_delete
    from packages.model_gateway.client import chat

    # Get all current memories
    all_memories = mem0_get_all(user_id=user_id)

    if len(all_memories) < 3:
        logger.info("Skipping consolidation for user %s: only %d memories", user_id, len(all_memories))
        return {
            "status": "skipped",
            "reason": "Too few memories to consolidate",
            "memory_count": len(all_memories),
        }

    # Format memories for the LLM
    memory_lines = []
    for i, mem in enumerate(all_memories, 1):
        mem_text = mem.get("memory", mem.get("content", ""))
        mem_id = mem.get("id", f"mem_{i}")
        memory_lines.append(f"  [{mem_id}] {mem_text}")

    memories_text = "\n".join(memory_lines)

    # Ask LLM to consolidate
    prompt = CONSOLIDATION_PROMPT.format(memories=memories_text)
    messages = [{"role": "user", "content": prompt}]

    try:
        response = await chat(messages, model=model, temperature=0.1)
    except Exception as exc:
        logger.error("Consolidation LLM call failed: %s", exc)
        return {"status": "error", "error": str(exc)}

    # Parse the LLM response
    kept = 0
    removed = 0
    merged = 0
    actions_taken = []

    for line in response.strip().split("\n"):
        line = line.strip()
        if line.startswith("REMOVE:"):
            parts = line.split("|")
            reason = parts[1].replace("REASON:", "").strip() if len(parts) > 1 else "duplicate/stale"

            # Find and delete the memory
            for mem in all_memories:
                mem_text = mem.get("memory", mem.get("content", ""))
                if mem_text and mem_text in line:
                    try:
                        await asyncio.to_thread(mem0_delete, mem["id"])
                        removed = int(removed) + 1
                        actions_taken.append({"action": "removed", "reason": reason, "id": mem["id"]})
                    except Exception:
                        pass
                    break

        elif line.startswith("MERGE:"):
            parts = line.split("|")
            new_text = parts[0].replace("MERGE:", "").strip()
            if new_text:
                try:
                    await asyncio.to_thread(mem0_add, new_text, user_id=user_id)
                    merged = int(merged) + 1
                    actions_taken.append({"action": "merged", "new_text": new_text[:100]})
                except Exception:
                    pass

        elif line.startswith("KEEP:"):
            kept = int(kept) + 1

    reset_turn_count(user_id)

    result = {
        "status": "completed",
        "kept": kept,
        "removed": removed,
        "merged": merged,
        "original_count": len(all_memories),
        "actions": actions_taken[:20],  # Cap logged actions
    }

    logger.info(
        "Consolidation for user %s: kept=%d, removed=%d, merged=%d (was %d)",
        user_id, kept, removed, merged, len(all_memories),
    )

    return result
