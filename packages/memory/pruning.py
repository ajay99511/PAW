"""
Session Pruning (Layer 3 of 5-Layer Memory System)

In-memory session pruning before each LLM call.
Trims old tool results to stay within context limits.

Key Features:
- TTL-based pruning (default 5 minutes)
- Protects last N assistant messages
- Soft-trim (keeps head + tail, inserts "...")
- Does NOT rewrite JSONL files (in-memory only)

Usage:
    from packages.memory.pruning import prune_messages
    
    pruned = await prune_messages(
        messages,
        ttl_seconds=300,
        protect_last_n=3,
        max_tokens=8000,
    )
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Default pruning configuration
DEFAULT_TTL_SECONDS = 300  # 5 minutes
DEFAULT_PROTECT_LAST_N = 3
DEFAULT_SOFT_TRIM_THRESHOLD = 0.8  # Start soft trim at 80% of limit


async def prune_messages(
    messages: list[dict[str, Any]],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    protect_last_n: int = DEFAULT_PROTECT_LAST_N,
    max_tokens: int | None = None,
    estimate_tokens: bool = True,
) -> list[dict[str, Any]]:
    """
    Prune old tool results from messages list (in-memory only).
    
    Args:
        messages: List of message dicts to prune
        ttl_seconds: TTL for tool results (older results get pruned)
        protect_last_n: Number of recent messages to protect from pruning
        max_tokens: Optional max token limit (prunes until under limit)
        estimate_tokens: Whether to estimate tokens for max_tokens check
    
    Returns:
        Pruned messages list
    """
    if not messages:
        return messages
    
    now = datetime.now()
    pruned = []
    tool_result_count = 0

    # Protect the last N non-tool messages.
    # Tool results are always eligible for TTL pruning.
    protected_indices: set[int] = set()
    remaining_to_protect = max(0, protect_last_n)
    for idx in range(len(messages) - 1, -1, -1):
        if remaining_to_protect <= 0:
            break
        if messages[idx].get("role") != "tool":
            protected_indices.add(idx)
            remaining_to_protect -= 1

    for idx, msg in enumerate(messages):
        if msg.get("role") == "tool":
            msg_time = _get_message_timestamp(msg)
            if msg_time:
                age = (now - msg_time).total_seconds()
                if age > ttl_seconds:
                    pruned.append(
                        {
                            "role": "tool",
                            "content": "[Old tool result content cleared]",
                        }
                    )
                    tool_result_count += 1
                else:
                    pruned.append(msg)
            else:
                pruned.append(msg)
            continue

        # Protected non-tool messages are always preserved as-is.
        if idx in protected_indices:
            pruned.append(msg)
        else:
            pruned.append(msg)
    
    # Apply token limit if specified
    if max_tokens:
        pruned = _apply_token_limit(pruned, max_tokens, estimate_tokens)
    
    if tool_result_count > 0:
        logger.debug(f"Pruned {tool_result_count} old tool results")
    
    return pruned


def _get_message_timestamp(msg: dict[str, Any]) -> datetime | None:
    """Extract timestamp from message metadata."""
    # Check for _timestamp field (added by session manager)
    if "_timestamp" in msg:
        try:
            return datetime.fromisoformat(msg["_timestamp"])
        except (ValueError, TypeError):
            pass
    
    # Check metadata field
    metadata = msg.get("metadata", {})
    if "timestamp" in metadata:
        try:
            return datetime.fromisoformat(metadata["timestamp"])
        except (ValueError, TypeError):
            pass
    
    return None


def _apply_token_limit(
    messages: list[dict[str, Any]],
    max_tokens: int,
    estimate_tokens: bool = True,
) -> list[dict[str, Any]]:
    """
    Apply token limit by trimming oldest messages first.
    
    Args:
        messages: Messages to trim
        max_tokens: Maximum token budget
        estimate_tokens: Whether to use token estimation
    
    Returns:
        Trimmed messages list
    """
    if not messages:
        return messages
    
    # Estimate current token count
    current_tokens = _estimate_tokens(messages) if estimate_tokens else len(str(messages)) // 4
    
    if current_tokens <= max_tokens:
        return messages
    
    # Keep head (system messages) and tail (recent messages)
    head = []
    tail = []
    
    # Find system messages (always keep)
    for msg in messages:
        if msg.get("role") == "system":
            head.append(msg)
        else:
            break
    
    # Calculate how many recent messages to keep
    remaining_budget = max_tokens - _estimate_tokens(head)
    messages_per_token = len(messages) / current_tokens if current_tokens > 0 else 1
    messages_to_keep = int(remaining_budget * messages_per_token * 0.9)  # 10% safety margin
    
    # Keep most recent messages
    if messages_to_keep > 0:
        tail = messages[-messages_to_keep:]
    
    # Insert soft trim marker
    if head and tail:
        trimmed_count = len(messages) - len(head) - len(tail)
        if trimmed_count > 0:
            tail.insert(0, {
                "role": "system",
                "content": f"[... {trimmed_count} older messages trimmed for brevity ...]",
            })
    
    result = head + tail
    logger.debug(
        f"Applied token limit: {current_tokens} → {_estimate_tokens(result)} tokens, "
        f"kept {len(result)} of {len(messages)} messages"
    )
    
    return result


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """
    Rough token estimation (1 token ≈ 4 characters for English).
    
    Args:
        messages: Messages to estimate
    
    Returns:
        Estimated token count
    """
    total_chars = 0
    
    for msg in messages:
        # Count content
        content = msg.get("content", "")
        message_chars = 0
        if isinstance(content, str):
            message_chars += len(content)
        elif isinstance(content, (dict, list)):
            message_chars += len(str(content))
        
        # Count role and other fields
        message_chars += len(msg.get("role", ""))
        for key, value in msg.items():
            if key != "content" and isinstance(value, str):
                message_chars += len(value)

        # Add per-message structural overhead (JSON keys/metadata/separators).
        total_chars += message_chars + 16
    
    # Rough estimation: 1 token ≈ 4 chars, but never return 0 for non-empty input.
    return max(1, math.ceil(total_chars / 4))


async def soft_trim(
    messages: list[dict[str, Any]],
    threshold_ratio: float = DEFAULT_SOFT_TRIM_THRESHOLD,
    max_tokens: int = 128_000,
) -> list[dict[str, Any]]:
    """
    Apply soft trim when approaching token limit.
    
    Keeps head + tail, inserts "..." in middle.
    
    Args:
        messages: Messages to trim
        threshold_ratio: Ratio at which to start trimming (0.8 = 80%)
        max_tokens: Maximum token budget
    
    Returns:
        Soft-trimmed messages list
    """
    current_tokens = _estimate_tokens(messages)
    threshold = max_tokens * threshold_ratio
    
    if current_tokens <= threshold:
        return messages
    
    # Keep 20% head and 80% tail
    head_count = max(1, int(len(messages) * 0.2))
    tail_count = max(3, len(messages) - head_count)
    
    head = messages[:head_count]
    tail = messages[-tail_count:]
    
    # Insert trim marker
    trimmed_count = len(messages) - len(head) - len(tail)
    if trimmed_count > 0:
        tail.insert(0, {
            "role": "system",
            "content": f"[... {trimmed_count} messages omitted for brevity ...]",
        })
    
    result = head + tail
    
    # Ensure we actually reduced the message count
    if len(result) >= len(messages):
        # Force more aggressive trimming
        head_count = max(1, len(messages) // 4)
        tail_count = max(3, len(messages) // 2)
        head = messages[:head_count]
        tail = messages[-tail_count:]
        
        trimmed_count = len(messages) - len(head) - len(tail)
        if trimmed_count > 0:
            tail.insert(0, {
                "role": "system",
                "content": f"[... {trimmed_count} messages omitted for brevity ...]",
            })
        result = head + tail
    
    logger.debug(
        f"Soft trim applied: {len(messages)} → {len(result)} messages "
        f"({current_tokens} → {_estimate_tokens(result)} tokens)"
    )
    
    return result


async def hard_clear(
    messages: list[dict[str, Any]],
    protect_last_n: int = 3,
) -> list[dict[str, Any]]:
    """
    Hard clear old tool results (more aggressive than soft trim).
    
    Replaces old tool results with clear message.
    
    Args:
        messages: Messages to clear
        protect_last_n: Number of recent messages to protect
    
    Returns:
        Hard-cleared messages list
    """
    protected = messages[-protect_last_n:] if protect_last_n > 0 else []
    to_clear = messages[:-protect_last_n] if protect_last_n < len(messages) else []
    
    cleared = []
    clear_count = 0
    
    for msg in to_clear:
        if msg.get("role") == "tool":
            cleared.append({
                "role": "tool",
                "content": "[Old tool result content cleared]",
            })
            clear_count += 1
        else:
            cleared.append(msg)
    
    cleared.extend(protected)
    
    if clear_count > 0:
        logger.debug(f"Hard cleared {clear_count} tool results")
    
    return cleared


def get_pruning_config(
    model_provider: str = "ollama",
    context_window: int = 8_000,
) -> dict[str, Any]:
    """
    Get pruning configuration optimized for specific model.
    
    Args:
        model_provider: Model provider (ollama, anthropic, openai, etc.)
        context_window: Model's context window in tokens
    
    Returns:
        Pruning configuration dict
    """
    # Base configuration
    config = {
        "ttl_seconds": DEFAULT_TTL_SECONDS,
        "protect_last_n": DEFAULT_PROTECT_LAST_N,
        "soft_trim_threshold": DEFAULT_SOFT_TRIM_THRESHOLD,
        "max_tokens": context_window - 4_000,  # Reserve 4K tokens
    }
    
    # Provider-specific adjustments
    if model_provider == "anthropic":
        # Anthropic has cache TTL considerations
        config["ttl_seconds"] = 300  # 5 minutes matches cache TTL
        config["protect_last_n"] = 5  # Protect more for cache efficiency
    
    elif model_provider == "openai":
        # OpenAI can handle longer contexts
        config["protect_last_n"] = 3
    
    elif model_provider == "ollama":
        # Local models often have smaller contexts
        config["protect_last_n"] = 2
        config["soft_trim_threshold"] = 0.7  # Start trimming earlier
    
    return config
