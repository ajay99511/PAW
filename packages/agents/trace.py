"""
Agent Trace — real-time visibility into agent execution steps via SSE.

Provides a trace event model and an async collector that agents push
events into. The SSE endpoint reads from this collector.

Usage:
    from packages.agents.trace import trace_manager, TraceEvent

    # Agent pushes events
    trace_manager.emit(run_id, TraceEvent(agent="planner", event_type="thinking", content="..."))

    # SSE endpoint reads events
    async for event in trace_manager.stream(run_id):
        yield f"data: {event.model_dump_json()}\n\n"
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────


class TraceEvent(BaseModel):
    """A single agent execution trace event."""
    run_id: str = ""
    agent_name: str                                      # "planner", "researcher", "synthesizer"
    event_type: str                                      # "thinking", "tool_call", "tool_result", "output", "error"
    content: str                                         # Human-readable description
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    metadata: dict = Field(default_factory=dict)         # Extra data (tool args, scores, etc.)


# ── Trace Collector ──────────────────────────────────────────────────


class TraceCollector:
    """
    Thread-safe async trace event manager.

    Each run_id gets its own asyncio.Queue. Agents push events via emit(),
    SSE endpoints consume via stream().
    """

    def __init__(self):
        self._queues: dict[str, asyncio.Queue[TraceEvent | None]] = {}
        self._lock = asyncio.Lock()

    def new_run(self) -> str:
        """Create a new trace run and return its ID."""
        run_id = str(uuid.uuid4())[:8]
        self._queues[run_id] = asyncio.Queue()
        logger.info("Trace run started: %s", run_id)
        return run_id

    async def emit(self, run_id: str, event: TraceEvent) -> None:
        """Push a trace event for a given run."""
        event.run_id = run_id
        if run_id in self._queues:
            await self._queues[run_id].put(event)
            logger.debug("Trace [%s] %s: %s", run_id, event.agent_name, event.event_type)

    async def finish(self, run_id: str) -> None:
        """Signal that a run is complete (sends sentinel)."""
        if run_id in self._queues:
            await self._queues[run_id].put(None)
            logger.info("Trace run finished: %s", run_id)

    async def stream(self, run_id: str, timeout: float = 120.0) -> AsyncIterator[TraceEvent]:
        """
        Async generator yielding trace events for a run.
        Stops when the run finishes (None sentinel) or timeout expires.
        """
        if run_id not in self._queues:
            return

        queue = self._queues[run_id]
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning("Trace stream timeout for run %s", run_id)
                    return

                if event is None:
                    return  # Run finished
                yield event
        finally:
            # Cleanup
            self._queues.pop(run_id, None)

    def has_run(self, run_id: str) -> bool:
        """Check if a run exists."""
        return run_id in self._queues


# ── Singleton ────────────────────────────────────────────────────────

trace_manager = TraceCollector()
