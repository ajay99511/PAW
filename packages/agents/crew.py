"""
Agent Crew — lightweight Planner → Researcher → Synthesizer pipeline.

Uses LiteLLM directly (no CrewAI/LangChain dependency) for a minimal,
high-performance multi-agent orchestration pattern. Each "agent" is an
async function with a focused system prompt that runs sequentially.

The pipeline:
  1. Planner   — decomposes the user request into actionable steps
  2. Researcher — gathers context using memory/document search tools
  3. Synthesizer — produces the final response using plan + research

Usage:
    from packages.agents.crew import run_crew

    result = await run_crew("How should I structure my API?", user_id="default")
"""

from __future__ import annotations

import json
import logging
from typing import Any

from packages.model_gateway.client import chat
from packages.agents.tools import (
    search_user_memories,
    search_documents,
    format_tool_results,
)
from packages.agents.trace import trace_manager, TraceEvent
from packages.memory.memory_service import build_context, extract_and_store_from_turn

logger = logging.getLogger(__name__)


# ── Agent Prompts ────────────────────────────────────────────────────

PLANNER_SYSTEM = """You are the Planner agent (Architect role) in a multi-agent system.
Your job is to analyze the user's request and create a clear, actionable plan.

Given the user's message and any available context, produce:
1. A brief analysis of what the user needs
2. 2-5 numbered steps to address it
3. What information the Researcher should look for
4. Any special considerations (user preferences, project context)

Be concise and specific. Output your plan in plain text, NOT JSON."""

RESEARCHER_SYSTEM = """You are the Researcher agent (Librarian role) in a multi-agent system.
Your job is to gather and organize information based on the Planner's instructions.

You have been given:
- The original user request
- The Planner's research plan
- Context from memory and documents (if available)

Produce structured research notes:
1. Key facts and findings relevant to each plan step
2. Specific details from any provided context
3. Any gaps or uncertainties
4. Recommendations based on your findings

Be thorough but concise. Focus on actionable information."""

SYNTHESIZER_SYSTEM = """You are the Synthesizer agent (Writer role) in a multi-agent system.
Your job is to produce the final, polished response for the user.

You have been given:
- The original user request
- The Planner's plan
- The Researcher's findings
- User preferences and context

Produce a clear, well-structured response that:
1. Directly answers the user's question
2. Incorporates relevant research findings
3. Respects the user's known preferences and style
4. Is actionable and practical

Write naturally and helpfully — this is what the user will see."""


# ── Pipeline Execution ───────────────────────────────────────────────


async def run_crew(
    user_message: str,
    user_id: str = "default",
    model: str = "local",
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute the full Planner → Researcher → Synthesizer pipeline.

    Args:
        user_message: The user's input.
        user_id:      User ID for memory lookups.
        model:        Model key for LiteLLM.
        run_id:       Optional trace run ID for SSE streaming.

    Returns:
        Dict with 'response', 'plan', 'research', 'model_used', 'run_id'.
    """
    # Create trace run if not provided
    emit_traces = run_id is not None
    if run_id is None:
        run_id = trace_manager.new_run()

    try:
        # ── Step 0: Gather context ───────────────────────────────
        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="system",
                event_type="thinking",
                content="Gathering context from memory and documents...",
            ))

        context = ""
        try:
            context = await build_context(user_message, user_id=user_id)
        except Exception as exc:
            logger.warning("Context build failed: %s", exc)

        # ── Step 1: Planner ──────────────────────────────────────
        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="planner",
                event_type="thinking",
                content="Analyzing request and creating execution plan...",
            ))

        planner_messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
        ]
        if context:
            planner_messages.append({
                "role": "system",
                "content": f"Available context:\n{context}",
            })
        planner_messages.append({"role": "user", "content": user_message})

        plan = await chat(planner_messages, model=model, temperature=0.3)

        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="planner",
                event_type="output",
                content=plan[:500],
            ))

        # ── Step 2: Researcher ───────────────────────────────────
        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="researcher",
                event_type="thinking",
                content="Searching memories and documents...",
            ))

        # Use tools to gather more context
        memories = await search_user_memories(user_message, user_id=user_id)
        documents = await search_documents(user_message)
        tool_context = await format_tool_results(memories, documents)

        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="researcher",
                event_type="tool_result",
                content=f"Found {len(memories)} memories, {len(documents)} documents",
                metadata={"memory_count": len(memories), "doc_count": len(documents)},
            ))

        researcher_messages = [
            {"role": "system", "content": RESEARCHER_SYSTEM},
            {"role": "user", "content": (
                f"## Original Request\n{user_message}\n\n"
                f"## Plan\n{plan}\n\n"
                f"## Available Context\n{tool_context}"
            )},
        ]

        research = await chat(researcher_messages, model=model, temperature=0.3)

        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="researcher",
                event_type="output",
                content=research[:500],
            ))

        # ── Step 3: Synthesizer ──────────────────────────────────
        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="synthesizer",
                event_type="thinking",
                content="Producing final response...",
            ))

        synthesizer_messages = [
            {"role": "system", "content": SYNTHESIZER_SYSTEM},
            {"role": "user", "content": (
                f"## Original Request\n{user_message}\n\n"
                f"## Plan\n{plan}\n\n"
                f"## Research Findings\n{research}\n\n"
                f"## User Context\n{context or 'No user context available.'}"
            )},
        ]

        final_response = await chat(synthesizer_messages, model=model, temperature=0.7)

        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="synthesizer",
                event_type="output",
                content=final_response[:500],
            ))

        # ── Step 4: Auto-learn from the interaction ──────────────
        try:
            turn_messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": final_response},
            ]
            await extract_and_store_from_turn(turn_messages, user_id=user_id)
        except Exception as exc:
            logger.warning("Post-crew memory extraction failed: %s", exc)

        return {
            "response": final_response,
            "plan": plan,
            "research": research,
            "model_used": model,
            "run_id": run_id,
        }

    except Exception as exc:
        if emit_traces:
            await trace_manager.emit(run_id, TraceEvent(
                agent_name="system",
                event_type="error",
                content=str(exc),
            ))
        raise
    finally:
        if emit_traces:
            await trace_manager.finish(run_id)
