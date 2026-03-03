"""
Ingestion Orchestrator — crawl directories and index files into Qdrant.

Usage:
    from packages.tools.ingest import ingest_directory, ingest_file

    # Index an entire project
    report = await ingest_directory("C:/projects/my-app", recursive=True)

    # Index a single file
    report = await ingest_file("C:/docs/notes.md")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.tools.parsers import parse_file, detect_file_type, _EXTENSION_MAP
from packages.tools.chunker import chunk_document

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

# Directories and files to always skip during crawling
IGNORE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", "target", ".idea", ".vscode",
    "qdrant_data", "qdrant_storage",
}

IGNORE_FILES = {
    ".DS_Store", "Thumbs.db", ".gitignore", ".env",
    "package-lock.json", "yarn.lock", "poetry.lock",
}

# Max file size to process (5 MB)
MAX_FILE_SIZE = 5 * 1024 * 1024


# ── Data Models ──────────────────────────────────────────────────────


@dataclass
class IngestReport:
    """Report from a directory or file ingestion run."""
    total_files: int = 0
    processed_files: int = 0
    total_chunks: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    duration_seconds: float = 0.0
    files_processed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "total_chunks": self.total_chunks,
            "skipped_files": self.skipped_files,
            "failed_files": self.failed_files,
            "errors": self.errors[:10],  # Cap reported errors
            "duration_seconds": round(self.duration_seconds, 2),
            "files_processed": self.files_processed[:50],  # Cap file list
        }


# ── Public API ───────────────────────────────────────────────────────


async def ingest_directory(
    path: str,
    recursive: bool = True,
    glob_patterns: list[str] | None = None,
) -> IngestReport:
    """
    Crawl a directory and index all supported files into Qdrant.

    Args:
        path:          Directory path to crawl.
        recursive:     Whether to recurse into subdirectories.
        glob_patterns: Optional glob patterns to filter files (e.g. ["*.py", "*.md"]).

    Returns:
        IngestReport with processing statistics.
    """
    from packages.memory import qdrant_store

    start = time.time()
    report = IngestReport()

    dir_path = Path(path)
    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {path}")

    # Collect files
    files = _crawl_directory(dir_path, recursive, glob_patterns)
    report.total_files = len(files)

    logger.info("Found %d files to process in %s", len(files), path)

    # Ensure Qdrant collection exists
    await qdrant_store.init_collections()

    # Process each file
    for file_path in files:
        try:
            chunks_created = await _process_file(file_path, qdrant_store)
            report.processed_files += 1
            report.total_chunks += chunks_created
            report.files_processed.append(str(file_path))
        except Exception as exc:
            report.failed_files += 1
            report.errors.append({
                "file": str(file_path),
                "error": str(exc),
            })
            logger.error("Failed to process %s: %s", file_path, exc)

    report.duration_seconds = time.time() - start

    logger.info(
        "Ingestion complete: %d/%d files, %d chunks, %.1fs",
        report.processed_files, report.total_files,
        report.total_chunks, report.duration_seconds,
    )

    return report


async def ingest_file(path: str) -> IngestReport:
    """
    Index a single file into Qdrant.

    Args:
        path: File path to index.

    Returns:
        IngestReport with processing statistics.
    """
    from packages.memory import qdrant_store

    start = time.time()
    report = IngestReport(total_files=1)

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not file_path.is_file():
        raise ValueError(f"Not a file: {path}")

    await qdrant_store.init_collections()

    try:
        chunks_created = await _process_file(file_path, qdrant_store)
        report.processed_files = 1
        report.total_chunks = chunks_created
        report.files_processed.append(str(file_path))
    except Exception as exc:
        report.failed_files = 1
        report.errors.append({
            "file": str(file_path),
            "error": str(exc),
        })
        logger.error("Failed to process %s: %s", file_path, exc)

    report.duration_seconds = time.time() - start
    return report


# ── Internal Helpers ─────────────────────────────────────────────────


def _crawl_directory(
    root: Path,
    recursive: bool,
    glob_patterns: list[str] | None,
) -> list[Path]:
    """Walk a directory tree and collect supported files."""
    files = []

    if glob_patterns:
        # Use glob patterns to filter
        for pattern in glob_patterns:
            if recursive:
                matched = list(root.rglob(pattern))
            else:
                matched = list(root.glob(pattern))
            files.extend(matched)
    else:
        # Collect all supported files
        if recursive:
            all_files = root.rglob("*")
        else:
            all_files = root.glob("*")

        for f in all_files:
            if f.is_file() and f.suffix.lower() in _EXTENSION_MAP:
                files.append(f)

    # Filter out ignored directories and files
    filtered = []
    for f in files:
        if not f.is_file():
            continue

        # Check if any parent directory is in the ignore list
        parts = f.relative_to(root).parts
        if any(part in IGNORE_DIRS for part in parts[:-1]):
            continue

        # Check filename ignore list
        if f.name in IGNORE_FILES:
            continue

        # Check file size
        try:
            if f.stat().st_size > MAX_FILE_SIZE:
                logger.debug("Skipping large file: %s", f)
                continue
            if f.stat().st_size == 0:
                continue
        except OSError:
            continue

        filtered.append(f)

    return sorted(set(filtered))


async def _process_file(file_path: Path, store) -> int:
    """Parse, chunk, and upsert a single file. Returns chunk count."""
    # Parse
    doc = parse_file(file_path)

    if not doc.text.strip():
        return 0

    # Chunk
    chunks = chunk_document(doc)

    if not chunks:
        return 0

    # Upsert each chunk to Qdrant
    for chunk in chunks:
        metadata = {
            **chunk.metadata,
            "content_type": "document",
            "user_id": "default",
        }
        await store.upsert(
            text=chunk.text,
            metadata=metadata,
        )

    return len(chunks)
