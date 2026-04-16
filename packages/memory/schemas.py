"""
Memory Schemas — Pydantic models for the memory subsystem.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Categories of memories stored in the system."""
    PROFILE = "PROFILE"           # User preferences, traits, background
    PROJECT = "PROJECT"           # Ongoing project context
    EPISODE = "EPISODE"           # Conversation episodes / interactions
    TASK_OUTCOME = "TASK_OUTCOME" # Results of completed tasks


class MemoryItem(BaseModel):
    """A single memory entry to be stored in Qdrant."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "default"
    memory_type: MemoryType = MemoryType.PROFILE
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MemorySearchResult(BaseModel):
    """A memory item returned from a semantic search."""
    id: str
    content: str
    memory_type: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class Mem0Memory(BaseModel):
    """Legacy response shape for long-term memory API compatibility."""
    id: str
    memory: str
    user_id: str = "default"
    categories: list[str] = Field(default_factory=list)
    created_at: str | None = None
    score: float | None = None
