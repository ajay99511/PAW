"""
Tests for the agent trace streaming module.
"""

import asyncio
import pytest
from packages.agents.trace import TraceCollector, TraceEvent


@pytest.fixture
def collector():
    return TraceCollector()


class TestTraceCollector:
    """Tests for trace event management."""

    def test_new_run_returns_id(self, collector):
        run_id = collector.new_run()
        assert isinstance(run_id, str)
        assert len(run_id) == 8

    def test_has_run(self, collector):
        run_id = collector.new_run()
        assert collector.has_run(run_id) is True
        assert collector.has_run("nonexistent") is False

    @pytest.mark.asyncio
    async def test_emit_and_stream(self, collector):
        run_id = collector.new_run()

        event = TraceEvent(
            agent_name="planner",
            event_type="thinking",
            content="Analyzing...",
        )
        await collector.emit(run_id, event)
        await collector.finish(run_id)

        received = []
        async for e in collector.stream(run_id, timeout=2.0):
            received.append(e)

        assert len(received) == 1
        assert received[0].agent_name == "planner"
        assert received[0].content == "Analyzing..."

    @pytest.mark.asyncio
    async def test_finish_ends_stream(self, collector):
        run_id = collector.new_run()
        await collector.finish(run_id)

        received = []
        async for e in collector.stream(run_id, timeout=2.0):
            received.append(e)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_stream_nonexistent_run(self, collector):
        received = []
        async for e in collector.stream("nonexistent", timeout=1.0):
            received.append(e)
        assert len(received) == 0


class TestTraceEvent:
    """Tests for TraceEvent model."""

    def test_creation(self):
        event = TraceEvent(
            agent_name="researcher",
            event_type="tool_call",
            content="Searching documents...",
        )
        assert event.agent_name == "researcher"
        assert event.event_type == "tool_call"
        assert event.timestamp  # auto-populated

    def test_metadata_default_empty(self):
        event = TraceEvent(
            agent_name="test",
            event_type="test",
            content="test",
        )
        assert event.metadata == {}

    def test_serialization(self):
        event = TraceEvent(
            agent_name="test",
            event_type="output",
            content="Hello",
            metadata={"count": 5},
        )
        data = event.model_dump()
        assert "agent_name" in data
        assert data["metadata"]["count"] == 5
