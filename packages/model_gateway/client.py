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
from typing import AsyncIterator

import litellm

from packages.shared.config import settings

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────
# Suppress litellm printing to stdout
litellm.set_verbose = False


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
            if attempt < max_retries:
                wait = 2 ** attempt  # 1s, 2s
                logger.warning(
                    "model_gateway.chat attempt %d failed (%s), retrying in %ss…",
                    attempt + 1, exc, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error("model_gateway.chat failed after %d attempts", max_retries + 1)
    raise last_exc  # type: ignore[misc]


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

    response = await litellm.acompletion(**kwargs)
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


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
