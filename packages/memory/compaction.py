"""
Compaction Engine (Layer 4 of 5-Layer Memory System)

Adaptive session compaction when context approaches model limits.
Summarizes old conversation turns while preserving important information.

Key Features:
- Adaptive chunk ratio (0.15-0.40 based on message size)
- Multi-stage summarization with fallback
- Pre-compaction memory flush (silent turn)
- Atomic JSONL rewrite (temp file + rename)
- Preserves identifiers (UUIDs, IPs, URLs, file names)

Usage:
    from packages.memory.compaction import compact_session
    
    result = await compact_session(
        session_id="user_main",
        model="local",
    )
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from packages.memory.jsonl_store import (
    load_transcript,
    compact_transcript,
    get_session_stats,
    JSONLEntry,
)
from packages.memory.bootstrap import load_bootstrap_files
from packages.model_gateway.client import chat

logger = logging.getLogger(__name__)

# Compaction configuration
CONTEXT_WINDOW = 128_000  # tokens (adjust per model)
RESERVE_TOKENS = 4_000  # Reserve for new input/output
SOFT_THRESHOLD = 4_000  # Trigger compaction when this close to limit

# Chunking configuration
BASE_CHUNK_RATIO = 0.4
MIN_CHUNK_RATIO = 0.15
SAFETY_MARGIN = 1.2  # 20% safety margin for token estimation


@dataclass
class CompactionResult:
    """Result of a compaction operation."""
    
    skipped: bool
    reason: str
    summary: str | None = None
    entries_removed: int = 0
    entries_kept: int = 0
    tokens_before: int = 0
    tokens_after: int = 0


async def compact_session(
    session_id: str,
    model: str = "local",
    context_window: int = CONTEXT_WINDOW,
    reserve_tokens: int = RESERVE_TOKENS,
) -> CompactionResult:
    """
    Compact a session when context approaches limit.
    
    Args:
        session_id: Session to compact
        model: Model to use for summarization
        context_window: Model's context window
        reserve_tokens: Tokens to reserve for new input/output
    
    Returns:
        Compaction result
    """
    # Get current session stats
    stats = await get_session_stats(session_id)
    
    # Check if compaction needed
    threshold = context_window - reserve_tokens - SOFT_THRESHOLD
    if stats.estimated_tokens < threshold:
        logger.debug(
            f"Compaction not needed for {session_id}: "
            f"{stats.estimated_tokens} < {threshold} tokens"
        )
        return CompactionResult(
            skipped=True,
            reason="not_needed",
            tokens_before=stats.estimated_tokens,
        )
    
    logger.info(
        f"Starting compaction for {session_id}: "
        f"{stats.estimated_tokens} tokens (threshold: {threshold})"
    )
    
    # Pre-compaction memory flush (silent turn)
    await memory_flush_turn(session_id, model)
    
    # Load transcript
    entries = await load_transcript(session_id)
    messages = [e for e in entries if e.type == "message"]
    
    if len(messages) < 5:
        logger.warning(f"Session {session_id} too short for compaction")
        return CompactionResult(
            skipped=True,
            reason="too_short",
            tokens_before=stats.estimated_tokens,
        )
    
    # Compute adaptive chunk ratio
    avg_msg_tokens = stats.estimated_tokens / len(messages) if messages else 0
    ratio = compute_adaptive_chunk_ratio(avg_msg_tokens)
    
    logger.debug(
        f"Adaptive chunk ratio: {ratio} "
        f"(avg message: {avg_msg_tokens:.1f} tokens)"
    )
    
    # Chunk messages
    max_chunk_tokens = context_window * ratio
    chunks = chunk_messages_by_max_tokens(messages, max_chunk_tokens)
    
    logger.debug(f"Split into {len(chunks)} chunks for summarization")
    
    # Summarize with fallback
    summary = await summarize_with_fallback(chunks, model)
    
    if not summary:
        logger.error(f"Compaction summarization failed for {session_id}")
        return CompactionResult(
            skipped=True,
            reason="summarization_failed",
            tokens_before=stats.estimated_tokens,
        )
    
    # Preserve identifiers
    summary = preserve_identifiers(summary, messages)
    
    # Find first entry to keep (last chunk)
    first_kept_index = max(0, len(messages) - int(len(messages) * ratio))
    first_kept_entry = messages[first_kept_index] if first_kept_index < len(messages) else messages[-1]
    
    # Compact transcript
    success = await compact_transcript(
        session_id,
        summary,
        first_kept_entry.id,
    )
    
    if not success:
        logger.error(f"Failed to compact transcript for {session_id}")
        return CompactionResult(
            skipped=True,
            reason="compaction_failed",
            tokens_before=stats.estimated_tokens,
        )
    
    # Get new stats
    new_stats = await get_session_stats(session_id)
    
    result = CompactionResult(
        skipped=False,
        reason="success",
        summary=summary,
        entries_removed=stats.total_entries - new_stats.total_entries,
        entries_kept=new_stats.total_entries,
        tokens_before=stats.estimated_tokens,
        tokens_after=new_stats.estimated_tokens,
    )
    
    logger.info(
        f"Compaction complete for {session_id}: "
        f"removed {result.entries_removed} entries, "
        f"{result.tokens_before} → {result.tokens_after} tokens"
    )
    
    return result


async def memory_flush_turn(session_id: str, model: str = "local") -> None:
    """
    Silent turn to write durable memories before compaction.
    
    Args:
        session_id: Session to flush
        model: Model to use
    """
    from packages.agents.crew import run_crew
    
    try:
        logger.debug(f"Running memory flush for session {session_id}")
        
        result = await run_crew(
            user_message=(
                "Session nearing compaction. Write any lasting notes to MEMORY.md. "
                "Reply NO_REPLY if nothing to store."
            ),
            user_id=session_id.split("_")[0],  # Extract user_id from session_id
            model=model,
        )
        
        logger.debug(f"Memory flush completed: {result.get('response', '')[:100]}")
    
    except Exception as exc:
        logger.warning(f"Memory flush failed (non-fatal): {exc}")


def compute_adaptive_chunk_ratio(avg_message_tokens: float) -> float:
    """
    Compute adaptive chunk ratio based on average message size.
    
    Larger messages → smaller ratio (more aggressive compaction)
    Smaller messages → larger ratio (keep more history)
    
    Args:
        avg_message_tokens: Average tokens per message
    
    Returns:
        Chunk ratio between MIN_CHUNK_RATIO and BASE_CHUNK_RATIO
    """
    if avg_message_tokens <= 0:
        return BASE_CHUNK_RATIO
    
    # If average message > 10% of context, reduce ratio
    context_threshold = CONTEXT_WINDOW * 0.1
    
    if avg_message_tokens <= context_threshold:
        return BASE_CHUNK_RATIO
    
    # Linear interpolation
    ratio = BASE_CHUNK_RATIO - (avg_message_tokens / CONTEXT_WINDOW) * 0.25
    return max(ratio, MIN_CHUNK_RATIO)


def chunk_messages_by_max_tokens(
    messages: list[dict],
    max_tokens: int,
    safety_margin: float = SAFETY_MARGIN,
) -> list[list[dict]]:
    """
    Split messages into chunks respecting token spillover.
    
    Args:
        messages: Messages to chunk
        max_tokens: Maximum tokens per chunk
        safety_margin: Safety margin for token estimation error
    
    Returns:
        List of message chunks
    """
    if not messages:
        return []
    
    effective_max = max_tokens / safety_margin
    chunks = []
    current_chunk = []
    current_tokens = 0
    
    for msg in messages:
        msg_tokens = _estimate_message_tokens(msg)
        
        if current_tokens + msg_tokens > effective_max:
            # Start new chunk
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [msg]
            current_tokens = msg_tokens
        else:
            current_chunk.append(msg)
            current_tokens += msg_tokens
    
    # Add final chunk
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def _estimate_message_tokens(msg: dict) -> int:
    """Estimate tokens in a message (1 token ≈ 4 chars)."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return len(content) // 4
    elif isinstance(content, (dict, list)):
        return len(str(content)) // 4
    return 0


async def summarize_with_fallback(
    chunks: list[list[dict]],
    model: str = "local",
) -> str:
    """
    Summarize message chunks with multi-stage fallback.
    
    Stage 1: Full summarization (all chunks)
    Stage 2: Partial summarization (exclude oversized chunks)
    Stage 3: Size notes fallback
    
    Args:
        chunks: Message chunks to summarize
        model: Model to use
    
    Returns:
        Summary text
    """
    if not chunks:
        return ""
    
    # Stage 1: Full summarization
    try:
        summary = await _summarize_chunks(chunks, model)
        if summary and len(summary) > 100:
            return summary
    except Exception as exc:
        logger.warning(f"Full summarization failed: {exc}")
    
    # Stage 2: Partial summarization (exclude oversized)
    try:
        manageable_chunks = [
            chunk for chunk in chunks
            if sum(_estimate_message_tokens(m) for m in chunk) < 10_000
        ]
        
        if manageable_chunks:
            summary = await _summarize_chunks(manageable_chunks, model)
            if summary and len(summary) > 100:
                return summary
    except Exception as exc:
        logger.warning(f"Partial summarization failed: {exc}")
    
    # Stage 3: Size notes fallback
    total_messages = sum(len(chunk) for chunk in chunks)
    return f"[Previous conversation with {total_messages} messages summarized due to length constraints. Key topics and decisions should be inferred from context.]"


async def _summarize_chunks(chunks: list[list[dict]], model: str) -> str:
    """
    Summarize message chunks using LLM.
    
    Args:
        chunks: Message chunks
        model: Model to use
    
    Returns:
        Summary text
    """
    # Build prompt
    chunk_texts = []
    for i, chunk in enumerate(chunks, 1):
        chunk_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in chunk
        )
        chunk_texts.append(f"=== Conversation Segment {i} ===\n{chunk_text}")
    
    conversation_text = "\n\n".join(chunk_texts)
    
    # Truncate if too large
    if len(conversation_text) > 50_000:
        conversation_text = conversation_text[:50_000] + "\n[... truncated ...]"
    
    prompt = f"""
Please summarize the following conversation, preserving:
1. Key decisions and conclusions
2. Important facts and information
3. User preferences mentioned
4. Action items and next steps
5. Any identifiers (file paths, URLs, IDs, etc.)

Keep the summary concise but comprehensive. This summary will be used to maintain context in future conversation turns.

{conversation_text}
"""
    
    messages = [
        {"role": "system", "content": "You are an expert conversation summarizer. Create concise but comprehensive summaries that preserve key information, decisions, and context."},
        {"role": "user", "content": prompt},
    ]
    
    response = await chat(messages, model=model, temperature=0.3, max_tokens=2000)
    return response.strip()


def preserve_identifiers(summary: str, messages: list[dict]) -> str:
    """
    Ensure identifiers from original messages are preserved in summary.
    
    Identifiers include:
    - UUIDs
    - IP addresses
    - URLs
    - File paths
    - Email addresses
    - Code identifiers
    
    Args:
        summary: Summary text
        messages: Original messages
    
    Returns:
        Summary with identifiers preserved
    """
    # Extract identifiers from original messages
    identifiers = set()
    
    identifier_patterns = [
        r'\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b',  # UUID
        r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',  # IP address
        r'https?://[^\s<>"{}|\\^`\[\]]+',  # URL
        r'[A-Za-z]:\\[^\s<>"{}|\\^`\[\]]+',  # Windows path
        r'/[^\s<>"{}|\\^`\[\]]+',  # Unix path
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email
        r'\b[A-Z][a-zA-Z0-9_]{2,}\b',  # Code identifiers (CamelCase)
    ]
    
    for msg in messages:
        content = str(msg.get("content", ""))
        for pattern in identifier_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            identifiers.update(matches)
    
    # Check if identifiers are in summary
    missing_identifiers = []
    for identifier in identifiers:
        if identifier not in summary:
            missing_identifiers.append(identifier)
    
    # Append missing identifiers if significant
    if missing_identifiers and len(missing_identifiers) <= 20:
        summary += "\n\nPreserved identifiers: " + ", ".join(missing_identifiers[:10])
    
    return summary


async def should_compact(
    session_id: str,
    context_window: int = CONTEXT_WINDOW,
    reserve_tokens: int = RESERVE_TOKENS,
) -> bool:
    """
    Check if a session should be compacted.
    
    Args:
        session_id: Session to check
        context_window: Model's context window
        reserve_tokens: Tokens to reserve
    
    Returns:
        True if compaction should trigger
    """
    stats = await get_session_stats(session_id)
    threshold = context_window - reserve_tokens - SOFT_THRESHOLD
    
    return stats.estimated_tokens > threshold
