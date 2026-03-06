"""
Podcast Router — FastAPI endpoints for podcast generation.

Mounted as a sub-router on the main app. All endpoints are prefixed
with /api/podcast to keep them isolated from existing routes.

Endpoints:
  POST   /api/podcast/generate        Start a new podcast job
  GET    /api/podcast/status/{job_id}  Poll job status
  GET    /api/podcast/status/{job_id}/stream  SSE progress stream
  GET    /api/podcast/download/{job_id}  Download generated MP3
  GET    /api/podcast/jobs             List recent jobs
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from packages.agents.podcast_crew import (
    PodcastJob,
    PodcastRequest,
    run_podcast_crew,
)
from packages.agents.trace import trace_manager

logger = logging.getLogger(__name__)

# ── Router Setup ─────────────────────────────────────────────────────

podcast_router = APIRouter(
    prefix="/api/podcast",
    tags=["Podcast"],
)

# ── In-Memory Job Store ──────────────────────────────────────────────

_jobs: dict[str, PodcastJob] = {}
_MAX_JOBS = 50  # Keep last N jobs in memory


def _cleanup_jobs() -> None:
    """Remove oldest jobs if we exceed the max."""
    if len(_jobs) > _MAX_JOBS:
        sorted_ids = sorted(
            _jobs.keys(),
            key=lambda jid: _jobs[jid].created_at,
        )
        for jid in sorted_ids[: len(_jobs) - _MAX_JOBS]:
            _jobs.pop(jid, None)


# ── Request / Response Models ────────────────────────────────────────


class GenerateResponse(BaseModel):
    job_id: str
    status_url: str


class JobStatusResponse(BaseModel):
    job_id: str
    topic: str = ""
    status: str = "queued"
    progress_pct: int = 0
    output_path: str | None = None
    error: str | None = None
    created_at: str = ""
    duration_minutes: int = 0
    level: str = ""


# ── Endpoints ────────────────────────────────────────────────────────


@podcast_router.post("/generate", response_model=GenerateResponse)
async def generate_podcast(req: PodcastRequest):
    """
    Start a podcast generation job.

    Returns immediately with a job_id. The actual generation
    happens in the background via asyncio.create_task().
    """
    job_id = str(uuid.uuid4())[:12]

    # Create job record
    job = PodcastJob(
        job_id=job_id,
        topic=req.topic,
        duration_minutes=req.duration_minutes,
        level=req.level,
    )
    _jobs[job_id] = job
    _cleanup_jobs()

    # Create trace run for SSE streaming
    trace_run_id = trace_manager.new_run()

    # Progress callback that updates the in-memory job AND emits trace events
    async def _on_progress(status: str, pct: int) -> None:
        if job_id in _jobs:
            _jobs[job_id].status = status
            _jobs[job_id].progress_pct = pct

    # Fire and forget the generation
    async def _run():
        try:
            result = await run_podcast_crew(req, job_id, on_progress=_on_progress)
            _jobs[job_id] = result
        except Exception as exc:
            logger.error("Podcast job %s failed: %s", job_id, exc)
            if job_id in _jobs:
                _jobs[job_id].status = "error"
                _jobs[job_id].error = str(exc)

    asyncio.create_task(_run())

    logger.info("Podcast job started: %s (topic=%s)", job_id, req.topic)

    return GenerateResponse(
        job_id=job_id,
        status_url=f"/api/podcast/status/{job_id}",
    )


@podcast_router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Poll the status of a podcast generation job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    return JobStatusResponse(
        job_id=job.job_id,
        topic=job.topic,
        status=job.status,
        progress_pct=job.progress_pct,
        output_path=job.output_path,
        error=job.error,
        created_at=job.created_at,
        duration_minutes=job.duration_minutes,
        level=job.level,
    )


@podcast_router.get("/status/{job_id}/stream")
async def stream_job_progress(job_id: str):
    """
    SSE stream of real-time progress events for a podcast job.

    Yields JSON events with status and progress updates.
    Closes when the job completes, errors, or times out (5 min).
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    async def _generate():
        last_status = ""
        last_pct = -1
        timeout = 300  # 5 minutes max
        elapsed = 0

        while elapsed < timeout:
            current = _jobs.get(job_id)
            if not current:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                return

            # Emit only when something changed
            if current.status != last_status or current.progress_pct != last_pct:
                last_status = current.status
                last_pct = current.progress_pct
                yield f"data: {json.dumps(current.model_dump())}\n\n"

            # Terminal states
            if current.status in ("done", "error"):
                return

            await asyncio.sleep(1)
            elapsed += 1

        yield f"data: {json.dumps({'status': 'timeout'})}\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@podcast_router.get("/download/{job_id}")
async def download_podcast(job_id: str):
    """Download the generated podcast MP3 file."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if job.status != "done":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not complete (status: {job.status})",
        )

    if not job.output_path:
        raise HTTPException(status_code=500, detail="No output file path recorded")

    file_path = Path(job.output_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found on disk")

    return FileResponse(
        path=str(file_path),
        media_type="audio/mpeg",
        filename=file_path.name,
    )


@podcast_router.get("/jobs")
async def list_jobs():
    """List all recent podcast generation jobs."""
    jobs = sorted(
        _jobs.values(),
        key=lambda j: j.created_at,
        reverse=True,
    )
    return {
        "jobs": [j.model_dump() for j in jobs[:20]],
        "count": len(jobs),
    }
