"""
Tests for the Podcast Crew pipeline.

These tests validate the Pydantic models, curriculum planning logic,
and job lifecycle without requiring running services (Ollama, Qdrant).
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from packages.agents.podcast_crew import (
    PodcastCurriculum,
    PodcastModule,
    PodcastRequest,
    PodcastJob,
    _extract_json,
)


# ── Model Validation Tests ──────────────────────────────────────────


class TestPodcastModels:
    """Test Pydantic model validation for podcast schemas."""

    def test_valid_podcast_request(self):
        req = PodcastRequest(
            topic="Python Basics",
            duration_minutes=30,
            level="beginner",
        )
        assert req.topic == "Python Basics"
        assert req.duration_minutes == 30
        assert req.level == "beginner"
        assert req.model == "local"

    def test_duration_limits(self):
        # Min
        req = PodcastRequest(topic="Test", duration_minutes=15)
        assert req.duration_minutes == 15

        # Over max should raise
        with pytest.raises(Exception):
            PodcastRequest(topic="Test", duration_minutes=200)

    def test_empty_topic_rejected(self):
        with pytest.raises(Exception):
            PodcastRequest(topic="", duration_minutes=30)

    def test_valid_curriculum(self):
        curriculum = PodcastCurriculum(
            title="Test Podcast",
            modules=[
                PodcastModule(
                    title="Intro",
                    priority="high",
                    allocated_minutes=10,
                    search_queries=["python basics"],
                ),
                PodcastModule(
                    title="Advanced",
                    priority="medium",
                    allocated_minutes=20,
                    search_queries=["python advanced"],
                ),
            ],
            total_minutes=30,
        )
        assert len(curriculum.modules) == 2
        assert curriculum.total_minutes == 30

    def test_curriculum_needs_at_least_one_module(self):
        with pytest.raises(Exception):
            PodcastCurriculum(title="Empty", modules=[], total_minutes=0)

    def test_module_minutes_must_be_positive(self):
        with pytest.raises(Exception):
            PodcastModule(
                title="Bad",
                allocated_minutes=0,
                search_queries=[],
            )

    def test_podcast_job_defaults(self):
        job = PodcastJob(job_id="test123")
        assert job.status == "queued"
        assert job.progress_pct == 0
        assert job.output_path is None
        assert job.error is None


# ── JSON Extraction Tests ───────────────────────────────────────────


class TestJsonExtraction:
    """Test LLM response JSON extraction."""

    def test_plain_json(self):
        raw = '{"title": "Test", "modules": [], "total_minutes": 30}'
        result = _extract_json(raw)
        parsed = json.loads(result)
        assert parsed["title"] == "Test"

    def test_markdown_fenced_json(self):
        raw = "Here is the plan:\n```json\n{\"title\": \"Test\"}\n```"
        result = _extract_json(raw)
        parsed = json.loads(result)
        assert parsed["title"] == "Test"

    def test_json_with_surrounding_text(self):
        raw = "Sure! Here is the JSON:\n{\"title\": \"Test\"}\nHope this helps!"
        result = _extract_json(raw)
        parsed = json.loads(result)
        assert parsed["title"] == "Test"


# ── Duration Allocation Tests ───────────────────────────────────────


class TestDurationAllocation:
    """Test that module minutes properly sum to total."""

    def test_modules_sum_to_total(self):
        curriculum = PodcastCurriculum(
            title="Test",
            modules=[
                PodcastModule(
                    title="A", allocated_minutes=10, search_queries=["a"],
                ),
                PodcastModule(
                    title="B", allocated_minutes=15, search_queries=["b"],
                ),
                PodcastModule(
                    title="C", allocated_minutes=5, search_queries=["c"],
                ),
            ],
            total_minutes=30,
        )
        actual_sum = sum(m.allocated_minutes for m in curriculum.modules)
        assert actual_sum == curriculum.total_minutes

    def test_word_count_approximation(self):
        """Verify ~150 words/min calculation."""
        module = PodcastModule(
            title="Test", allocated_minutes=5, search_queries=[],
        )
        expected_words = module.allocated_minutes * 150
        assert expected_words == 750


# ── Job Lifecycle Tests ─────────────────────────────────────────────


class TestJobLifecycle:
    """Test job status transitions."""

    def test_initial_state(self):
        job = PodcastJob(job_id="j1", topic="Test Topic")
        assert job.status == "queued"
        assert job.progress_pct == 0

    def test_progress_update(self):
        job = PodcastJob(job_id="j1")
        job.status = "planning"
        job.progress_pct = 15
        assert job.status == "planning"
        assert job.progress_pct == 15

    def test_error_state(self):
        job = PodcastJob(job_id="j1")
        job.status = "error"
        job.error = "LLM failed"
        assert job.status == "error"
        assert job.error == "LLM failed"

    def test_done_state(self):
        job = PodcastJob(job_id="j1")
        job.status = "done"
        job.progress_pct = 100
        job.output_path = "/tmp/podcast.mp3"
        assert job.status == "done"
        assert job.output_path is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
