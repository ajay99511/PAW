"""
Podcast Crew — 4-agent pipeline for audio curriculum generation.

Pipeline: PodcastPlanner → PodcastResearcher → ScriptWriter → Producer

This is a standalone crew parallel to the main Planner→Researcher→Synthesizer
pipeline in crew.py. It shares infrastructure (LiteLLM, Qdrant, TraceCollector)
but has zero code entanglement with the existing chat crew.

Usage:
    from packages.agents.podcast_crew import run_podcast_crew, PodcastRequest

    job = await run_podcast_crew(
        PodcastRequest(topic="Rust Concurrency", duration_minutes=30, level="intermediate"),
        job_id="abc123",
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field, field_validator

from packages.model_gateway.client import chat
from packages.agents.trace import trace_manager, TraceEvent

logger = logging.getLogger(__name__)


# ── Pydantic Models ──────────────────────────────────────────────────


class PodcastModule(BaseModel):
    """A single module in the podcast curriculum."""
    title: str
    priority: Literal["high", "medium", "low"] = "medium"
    allocated_minutes: int = Field(ge=1, le=60)
    search_queries: list[str] = Field(default_factory=list, max_length=3)


class PodcastCurriculum(BaseModel):
    """Validated output from the Planner agent."""
    title: str = ""
    modules: list[PodcastModule] = Field(min_length=1, max_length=15)
    total_minutes: int = Field(ge=1, le=120)


class PodcastRequest(BaseModel):
    """User-facing request to generate a podcast."""
    topic: str = Field(min_length=1, max_length=500)
    duration_minutes: int = Field(ge=15, le=120, default=30)
    level: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    model: str = "local"
    client_id: str = "desktop"

    @field_validator("duration_minutes")
    @classmethod
    def cap_duration(cls, v: int) -> int:
        from packages.shared.config import settings
        max_dur = getattr(settings, "podcast_max_duration", 120)
        if v > max_dur:
            raise ValueError(f"Duration cannot exceed {max_dur} minutes")
        return v


class PodcastJob(BaseModel):
    """Tracks the state of a podcast generation job."""
    job_id: str
    topic: str = ""
    status: str = "queued"  # queued, planning, researching, writing, producing, done, error
    progress_pct: int = 0
    output_path: str | None = None
    error: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    duration_minutes: int = 0
    level: str = ""


# ── Agent System Prompts ─────────────────────────────────────────────


PODCAST_PLANNER_SYSTEM = """You are the Podcast Planner agent. Your job is to break a topic into
a time-boxed audio curriculum.

Given the user's topic, total duration, and expertise level, produce a JSON object:

{{
  "title": "Podcast title",
  "modules": [
    {{
      "title": "Module Title",
      "priority": "high|medium|low",
      "allocated_minutes": <integer>,
      "search_queries": ["query1", "query2"]  (max 3 per module)
    }}
  ],
  "total_minutes": <integer matching requested duration>
}}

Rules:
1. Module minutes MUST sum exactly to the requested total_minutes.
2. Core/foundational modules get "high" priority and more minutes.
3. For shorter durations, REDUCE the number of modules (cut nice-to-haves).
4. For "beginner" level: focus on fundamentals and analogies.
   For "intermediate": balance theory and practical patterns.
   For "advanced": focus on edge cases, internals, and trade-offs.
5. Each module should have 1-3 search queries that will find authoritative content.
6. Output ONLY valid JSON - no markdown, no commentary, no wrapping.

Guidelines for duration allocation:
- 15 min total: 2-3 modules
- 30 min total: 3-5 modules
- 60 min total: 5-8 modules
- 90+ min total: 6-10 modules"""

PODCAST_RESEARCHER_SYSTEM = """You are the Podcast Researcher agent. You receive research material
for a specific module of a podcast curriculum.

Your job is to produce a DENSE, fact-heavy summary that a scriptwriter
can use to create an engaging spoken segment.

Rules:
1. Focus on key concepts, not filler.
2. Include specific examples, numbers, and comparisons where available.
3. Note any authoritative sources ("According to the official docs...", "Research from MIT shows...").
4. If the material is thin, note gaps honestly — do not hallucinate.
5. Target approximately {target_words} words for this summary (this maps to {allocated_minutes} minutes of audio at 150 words/minute).
6. Structure your output as:
   - Key Concepts (bullet points)
   - Detailed Explanation (prose)
   - Notable Examples
   - Sources Referenced"""

SCRIPT_WRITER_SYSTEM = """You are the Podcast ScriptWriter agent. You convert research summaries
into engaging, spoken-word audio scripts.

Style guide:
- Write as if you are a knowledgeable radio host explaining to a curious friend.
- Use conversational language: "Let's dive into...", "Now here's the interesting part...", "Think of it like..."
- Include rhetorical questions: "But why does this matter?", "What happens when..."
- NEVER include code blocks. Instead, DESCRIBE code conceptually:
  "Imagine you have a function that takes a list and returns only the even numbers..."
- Include smooth transitions between topics.
- Attribute sources implicitly: "According to the official documentation...", "Researchers at Stanford found..."
- Start modules with a brief hook. End with a takeaway.

Constraints:
- Your script for this module MUST be approximately {target_words} words (±10%).
  This maps to about {allocated_minutes} minutes at spoken pace.
- Do NOT include stage directions, sound effects, or music cues.
- Output ONLY the spoken script text — no headers, no metadata."""

PRODUCER_INTRO_TEMPLATE = """Welcome to your personalized learning podcast. Today, we're exploring {topic}. \
This is a {level}-level session designed for about {duration} minutes. Let's get started."""

PRODUCER_OUTRO_TEMPLATE = """That wraps up our deep dive into {topic}. I hope you've picked up \
some valuable insights. Until next time, keep learning and stay curious."""


# ── Pipeline Execution ───────────────────────────────────────────────


async def run_podcast_crew(
    request: PodcastRequest,
    job_id: str,
    on_progress: Callable[[str, int], Awaitable[None]] | None = None,
) -> PodcastJob:
    """
    Execute the full Podcast pipeline:
    PodcastPlanner → PodcastResearcher → ScriptWriter → Producer.

    Args:
        request:     The podcast generation request.
        job_id:      Unique job identifier.
        on_progress: Optional async callback for progress updates.

    Returns:
        PodcastJob with final status and output path.
    """
    run_id = trace_manager.new_run()
    job = PodcastJob(
        job_id=job_id,
        topic=request.topic,
        duration_minutes=request.duration_minutes,
        level=request.level,
    )

    async def _progress(status: str, pct: int) -> None:
        job.status = status
        job.progress_pct = pct
        if on_progress:
            await on_progress(status, pct)
        await trace_manager.emit(run_id, TraceEvent(
            agent_name=f"podcast_{status}",
            event_type="progress",
            content=f"{status}: {pct}%",
            metadata={"job_id": job_id, "progress_pct": pct},
        ))

    try:
        # ── Step 1: Planning ─────────────────────────────────────
        await _progress("planning", 5)

        curriculum = await _run_planner(request)
        logger.info(
            "Podcast planned: %d modules, %d min total",
            len(curriculum.modules), curriculum.total_minutes,
        )
        await _progress("planning", 15)

        # ── Step 2: Research ─────────────────────────────────────
        await _progress("researching", 20)

        module_summaries = await _run_researcher(
            curriculum, request.model, on_progress=_progress,
        )
        await _progress("researching", 50)

        # ── Step 3: Script Writing ───────────────────────────────
        await _progress("writing", 55)

        full_script = await _run_script_writer(
            curriculum, module_summaries, request, on_progress=_progress,
        )
        await _progress("writing", 75)

        # ── Step 4: Audio Production ─────────────────────────────
        await _progress("producing", 80)

        output_path = await _run_producer(
            full_script, request, job_id, on_progress=_progress,
        )

        job.output_path = str(output_path)
        job.status = "done"
        job.progress_pct = 100
        await _progress("done", 100)

        logger.info("Podcast complete: %s -> %s", request.topic, output_path)
        return job

    except Exception as exc:
        logger.error("Podcast generation failed: %s", exc, exc_info=True)
        job.status = "error"
        job.error = str(exc)
        await trace_manager.emit(run_id, TraceEvent(
            agent_name="podcast_system",
            event_type="error",
            content=str(exc),
        ))
        return job

    finally:
        await trace_manager.finish(run_id)


# ── Individual Agent Implementations ─────────────────────────────────


async def _run_planner(request: PodcastRequest) -> PodcastCurriculum:
    """Planner Agent: breaks topic into a time-boxed curriculum."""

    messages = [
        {"role": "system", "content": PODCAST_PLANNER_SYSTEM},
        {"role": "user", "content": (
            f"Topic: {request.topic}\n"
            f"Duration: {request.duration_minutes} minutes\n"
            f"Level: {request.level}\n\n"
            "Generate the curriculum JSON now."
        )},
    ]

    raw = await chat(messages, model=request.model, temperature=0.2)

    # Extract JSON from response (handle potential markdown wrapping)
    json_str = _extract_json(raw)

    try:
        curriculum = PodcastCurriculum.model_validate_json(json_str)
    except Exception as exc:
        logger.warning("Planner JSON parse failed, attempting repair: %s", exc)
        curriculum = await _repair_curriculum_json(raw, request)

    # Validate total minutes
    actual_total = sum(m.allocated_minutes for m in curriculum.modules)
    if actual_total != curriculum.total_minutes:
        logger.warning(
            "Module sum (%d) != total (%d), adjusting",
            actual_total, curriculum.total_minutes,
        )
        curriculum.total_minutes = actual_total

    return curriculum


async def _run_researcher(
    curriculum: PodcastCurriculum,
    model: str,
    on_progress: Callable[[str, int], Awaitable[None]] | None = None,
) -> dict[str, str]:
    """Researcher Agent: fetches and summarizes content for each module."""
    from packages.tools.web_search import search_and_scrape

    module_summaries: dict[str, str] = {}
    total_modules = len(curriculum.modules)

    for idx, module in enumerate(curriculum.modules):
        module_id = f"mod_{idx}"
        target_words = module.allocated_minutes * 150

        # Progress update
        pct = 20 + int((idx / total_modules) * 30)
        if on_progress:
            await on_progress("researching", pct)

        # ── Gather research material ─────────────────────────────
        all_content: list[str] = []

        for query in module.search_queries[:3]:
            results = await search_and_scrape(query, max_urls=3)
            for r in results:
                content = r.get("content", "")
                if content:
                    source_url = r.get("url", "unknown")
                    all_content.append(
                        f"[Source: {source_url}]\n{content}"
                    )

        combined = "\n\n---\n\n".join(all_content) if all_content else "No research material found."

        # ── Chunk and store in Qdrant (optional, for freshness) ──
        await _store_research_in_qdrant(module_id, module.title, combined)

        # ── LLM summarization ────────────────────────────────────
        researcher_prompt = PODCAST_RESEARCHER_SYSTEM.format(
            target_words=target_words,
            allocated_minutes=module.allocated_minutes,
        )

        messages = [
            {"role": "system", "content": researcher_prompt},
            {"role": "user", "content": (
                f"## Module: {module.title}\n"
                f"## Priority: {module.priority}\n"
                f"## Target: ~{target_words} words\n\n"
                f"## Research Material:\n{combined[:8000]}"
            )},
        ]

        summary = await chat(messages, model=model, temperature=0.3)
        module_summaries[module_id] = summary

        logger.info("Researched module '%s': %d chars summary", module.title, len(summary))

    return module_summaries


async def _run_script_writer(
    curriculum: PodcastCurriculum,
    module_summaries: dict[str, str],
    request: PodcastRequest,
    on_progress: Callable[[str, int], Awaitable[None]] | None = None,
) -> str:
    """ScriptWriter Agent: converts summaries into spoken dialogue."""

    script_parts: list[str] = []

    # Intro
    intro = PRODUCER_INTRO_TEMPLATE.format(
        topic=request.topic,
        level=request.level,
        duration=request.duration_minutes,
    )
    script_parts.append(intro)

    total_modules = len(curriculum.modules)

    for idx, module in enumerate(curriculum.modules):
        module_id = f"mod_{idx}"
        summary = module_summaries.get(module_id, "")
        target_words = module.allocated_minutes * 150

        pct = 55 + int((idx / total_modules) * 20)
        if on_progress:
            await on_progress("writing", pct)

        writer_prompt = SCRIPT_WRITER_SYSTEM.format(
            target_words=target_words,
            allocated_minutes=module.allocated_minutes,
        )

        messages = [
            {"role": "system", "content": writer_prompt},
            {"role": "user", "content": (
                f"## Module: {module.title} (Module {idx + 1} of {total_modules})\n"
                f"## Level: {request.level}\n"
                f"## Target word count: ~{target_words} words\n\n"
                f"## Research Summary:\n{summary}\n\n"
                "Write the spoken script for this module now."
            )},
        ]

        script = await chat(messages, model=request.model, temperature=0.7)
        script_parts.append(script)

        logger.info(
            "Script for module '%s': %d words (target: %d)",
            module.title, len(script.split()), target_words,
        )

    # Outro
    outro = PRODUCER_OUTRO_TEMPLATE.format(topic=request.topic)
    script_parts.append(outro)

    return "\n\n".join(script_parts)


async def _run_producer(
    full_script: str,
    request: PodcastRequest,
    job_id: str,
    on_progress: Callable[[str, int], Awaitable[None]] | None = None,
) -> Path:
    """Producer Agent: synthesizes audio from the script."""
    from packages.tools.tts import synthesize_script, stitch_audio, get_tts_provider
    from packages.shared.config import settings

    # Resolve output directory
    output_dir_str = getattr(settings, "podcast_output_dir", "~/Downloads")
    output_base = Path(os.path.expanduser(output_dir_str))
    output_base.mkdir(parents=True, exist_ok=True)

    # Temp directory for segments
    segments_dir = output_base / f".podcast_tmp_{job_id}"
    segments_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Split script into paragraphs
        paragraphs = [p.strip() for p in full_script.split("\n\n") if p.strip()]

        if not paragraphs:
            raise ValueError("Script is empty — nothing to synthesize")

        if on_progress:
            await on_progress("producing", 85)

        # Synthesize all paragraphs
        provider = get_tts_provider()
        audio_files = await synthesize_script(
            paragraphs, segments_dir, provider=provider,
        )

        if not audio_files:
            raise ValueError("No audio segments produced")

        if on_progress:
            await on_progress("producing", 95)

        # Stitch into final MP3
        safe_topic = "".join(
            c if c.isalnum() or c in " _-" else "_"
            for c in request.topic
        )[:50].strip()
        filename = f"Podcast_{safe_topic}_{job_id[:6]}.mp3"
        final_path = output_base / filename

        await stitch_audio(audio_files, final_path)

        return final_path

    finally:
        # Cleanup temp segments
        import shutil
        try:
            shutil.rmtree(segments_dir, ignore_errors=True)
        except Exception:
            pass


# ── Helpers ──────────────────────────────────────────────────────────


def _extract_json(text: str) -> str:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = text.strip()

    # Try to find JSON in code fences
    import re
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # Try to find raw JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        return text[brace_start : brace_end + 1]

    return text


async def _repair_curriculum_json(raw: str, request: PodcastRequest) -> PodcastCurriculum:
    """Attempt to repair malformed JSON from the Planner via a follow-up call."""
    repair_messages = [
        {"role": "system", "content": (
            "You are a JSON repair agent. The following text is supposed to be a valid JSON "
            "curriculum but it has syntax errors. Fix it and output ONLY the corrected JSON."
        )},
        {"role": "user", "content": raw},
    ]

    repaired = await chat(repair_messages, model=request.model, temperature=0.0)
    json_str = _extract_json(repaired)

    return PodcastCurriculum.model_validate_json(json_str)


async def _store_research_in_qdrant(
    module_id: str,
    module_title: str,
    content: str,
) -> None:
    """Store research content chunks in the podcast-specific Qdrant collection."""
    try:
        from packages.memory.qdrant_store import _embed, _get_client
        from packages.shared.config import settings
        from qdrant_client.models import PointStruct, VectorParams, Distance

        collection = getattr(settings, "podcast_qdrant_collection", "podcast_research")
        client = _get_client()

        # Ensure collection exists
        collections = client.get_collections().collections
        existing = {c.name for c in collections}
        if collection not in existing:
            client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )

        # Chunk and store (simple paragraphs)
        chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 50][:20]

        for i, chunk in enumerate(chunks):
            point_id = hashlib.sha256(
                f"{module_id}_{i}_{chunk[:100]}".encode()
            ).hexdigest()[:32]

            try:
                embedding = await _embed(chunk[:1000])
                client.upsert(
                    collection_name=collection,
                    points=[PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload={
                            "_content": chunk,
                            "module_id": module_id,
                            "module_title": module_title,
                            "indexed_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )],
                )
            except Exception as exc:
                logger.debug("Qdrant upsert failed for chunk %d: %s", i, exc)

    except Exception as exc:
        # Qdrant storage is optional — don't fail the pipeline
        logger.warning("Research storage to Qdrant failed (non-fatal): %s", exc)
