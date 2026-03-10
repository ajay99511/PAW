"""
Model Gateway — unified LLM interface via LiteLLM.

Usage:
    from packages.model_gateway.client import chat, chat_stream

    # Blocking call
    reply = await chat([{"role": "user", "content": "Hello"}], model="local")

    # Streaming (async generator)
    async for chunk in chat_stream([{"role": "user", "content": "Hello"}]):
        print(chunk, end="")
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import AsyncIterator

import litellm

from packages.shared.config import settings

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────
# Suppress litellm printing to stdout
litellm.set_verbose = False

# Pass API keys to LiteLLM via environment (LiteLLM reads these)
if settings.gemini_api_key:
    os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
if settings.anthropic_api_key:
    os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
if settings.openai_api_key:
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key


def _redact_sensitive(text: str) -> str:
    """Redact common API key patterns and query parameters from logs/errors."""
    redacted = text
    redacted = re.sub(r"(key=)[^&\s'\"]+", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED_GOOGLE_API_KEY]", redacted)
    redacted = re.sub(r"(api[_-]?key\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)
    return redacted


async def chat(
    messages: list[dict],
    model: str = "local",
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    max_retries: int = 2,
) -> str:
    """
    Send messages to an LLM and return the full response text.

    Args:
        messages:    OpenAI-format message list.
        model:       Short key ("local", "gemini", "claude") or a raw
                     LiteLLM model string like "ollama/mistral".
        temperature: Sampling temperature.
        max_tokens:  Max tokens in response (None = model default).
        max_retries: Retries with exponential backoff on transient errors.

    Returns:
        The assistant message content as a string.
    """
    resolved = settings.resolve_model(model)
    kwargs = _build_kwargs(resolved, messages, temperature, max_tokens)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await litellm.acompletion(**kwargs)
            return response.choices[0].message.content
        except Exception as exc:
            last_exc = exc
            safe_exc = _redact_sensitive(str(exc))
            if attempt < max_retries:
                wait = 2 ** attempt  # 1s, 2s
                logger.warning(
                    "model_gateway.chat attempt %d failed (%s), retrying in %ss...",
                    attempt + 1, safe_exc, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error("model_gateway.chat failed after %d attempts", max_retries + 1)

    safe_last = _redact_sensitive(str(last_exc)) if last_exc else "Unknown model error"
    raise RuntimeError(f"Model request failed: {safe_last}") from last_exc


async def chat_stream(
    messages: list[dict],
    model: str = "local",
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """
    Stream tokens from an LLM as an async generator.

    Yields:
        Individual text chunks as they arrive.
    """
    resolved = settings.resolve_model(model)
    kwargs = _build_kwargs(resolved, messages, temperature, max_tokens, stream=True)

    try:
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
    except Exception as exc:
        safe_exc = _redact_sensitive(str(exc))
        logger.error("model_gateway.chat_stream failed: %s", safe_exc)
        raise RuntimeError(f"Model stream failed: {safe_exc}") from exc


# ── Helpers ──────────────────────────────────────────────────────────

def _build_kwargs(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int | None,
    stream: bool = False,
) -> dict:
    """Build the kwargs dict for litellm.acompletion."""
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    # For Ollama models, ensure the api_base is set
    if model.startswith("ollama/"):
        kwargs["api_base"] = settings.ollama_api_base

    return kwargs
