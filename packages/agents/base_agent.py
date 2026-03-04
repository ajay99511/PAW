"""
Agent Skeletons — legacy placeholder classes that now delegate to the crew.

These exist to maintain backward compatibility with any older code that
might expect to instantiate a `PlannerAgent`. The new pattern is to
use `packages.agents.crew.run_crew` directly.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from packages.agents.crew import run_crew

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all agents."""

    name: str = "base"

    @abstractmethod
    async def run(self, context: str, message: str) -> str | dict[str, Any]:
        """Process a message with optional context and return a response."""
        ...


class PlannerAgent(BaseAgent):
    """
    Planner — delegates immediately to the lightweight crew orchestration.
    """

    name = "planner"

    async def run(self, context: str, message: str) -> dict[str, Any]:
        logger.info("PlannerAgent delegating to run_crew pipeline")
        return await run_crew(
            user_message=message,
            user_id="default",
            model="local",
        )


class ResearcherAgent(BaseAgent):
    """Legacy placeholder."""

    name = "researcher"

    async def run(self, context: str, message: str) -> str:
        return "Not implemented directly. Use packages.agents.crew.run_crew"


class SynthesizerAgent(BaseAgent):
    """Legacy placeholder."""

    name = "synthesizer"

    async def run(self, context: str, message: str) -> str:
        return "Not implemented directly. Use packages.agents.crew.run_crew"
