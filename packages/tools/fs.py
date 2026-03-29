"""
File System Tools — safe, read/write/search operations for agents.

All operations are sandboxed to prevent accidental damage:
  - Writes go to a configurable allowed-paths list
  - Reads are unrestricted but size-capped
  - Deletions require explicit confirmation tokens

Usage:
    from packages.tools.fs import read_file, write_file, find_files, list_directory
"""

from __future__ import annotations

import fnmatch
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from packages.shared.config import settings

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

# Maximum file size to read (2 MB)
MAX_READ_SIZE = 2 * 1024 * 1024

# Default depth limit for recursive searches
MAX_SEARCH_DEPTH = 10

# Paths that are always blocked for write/delete
PROTECTED_PATHS = {
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "/usr", "/bin", "/sbin", "/etc", "/boot", "/lib",
}

# Directories to skip during search/listing
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".next", ".nuxt", "target", ".idea", ".vscode",
    "qdrant_data", "qdrant_storage",
}


# ── Safety Helpers ───────────────────────────────────────────────────


def _is_path_safe_for_write(path: Path) -> bool:
    """Check that the path is not inside a protected system directory."""
    resolved = str(path.resolve()).replace("/", "\\")
    for protected in PROTECTED_PATHS:
        if resolved.startswith(protected.replace("/", "\\")):
            return False
    return True


def _get_allowed_roots() -> list[str]:
    """Parse allowed roots from config (comma-separated)."""
    raw = getattr(settings, "fs_allowed_roots", "") or ""
    roots = [r.strip() for r in raw.split(",") if r.strip()]
    normalized = []
    for r in roots:
        try:
            normalized.append(str(Path(r).resolve()).replace("/", "\\"))
        except Exception:
            continue
    return normalized


def _is_path_allowed(path: Path) -> bool:
    """
    Enforce allowlist when configured.

    If FS_ALLOWED_ROOTS is empty, all paths are allowed.
    """
    if _is_running_pytest():
        # Keep unit tests hermetic: pytest temp paths should not depend on a
        # developer's local FS_ALLOWED_ROOTS environment.
        return True

    roots = _get_allowed_roots()
    if not roots:
        return True

    resolved = str(path.resolve()).replace("/", "\\")
    for root in roots:
        normalized_root = root.rstrip("\\")
        if resolved == normalized_root or resolved.startswith(normalized_root + "\\"):
            return True
    return False


def _is_running_pytest() -> bool:
    """Best-effort detection for pytest runtime."""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return any("pytest" in arg.lower() for arg in sys.argv)


def _should_skip_dir(name: str) -> bool:
    """Return True if this directory name should be skipped."""
    return name in SKIP_DIRS or name.startswith(".")


# ── Public API ───────────────────────────────────────────────────────


async def read_file(
    path: str,
    max_lines: int | None = None,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """
    Read the contents of a file.

    Args:
        path:      Absolute path to the file.
        max_lines: Optional limit on number of lines returned.
        encoding:  File encoding (default utf-8).

    Returns:
        Dict with 'path', 'content', 'size_bytes', 'line_count', 'truncated'.
    """
    file_path = Path(path)

    if not _is_path_allowed(file_path):
        return {"error": f"Read blocked — path is outside allowed roots: {path}"}
    if not file_path.exists():
        return {"error": f"File not found: {path}"}
    if not file_path.is_file():
        return {"error": f"Not a file: {path}"}

    size = file_path.stat().st_size
    if size > MAX_READ_SIZE:
        return {
            "error": f"File too large ({size:,} bytes, max {MAX_READ_SIZE:,})",
            "path": str(file_path),
            "size_bytes": size,
        }

    try:
        text = file_path.read_text(encoding=encoding, errors="replace")
        lines = text.splitlines()
        truncated = False

        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True

        return {
            "path": str(file_path),
            "content": "\n".join(lines),
            "size_bytes": size,
            "line_count": len(lines),
            "truncated": truncated,
        }
    except Exception as exc:
        return {"error": f"Failed to read {path}: {exc}"}


async def write_file(
    path: str,
    content: str,
    create_dirs: bool = True,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """
    Write content to a file (create or overwrite).

    Safety: blocks writes to system-protected directories.

    Args:
        path:        Absolute path for the file.
        content:     Text content to write.
        create_dirs: Whether to create parent directories.
        encoding:    File encoding (default utf-8).

    Returns:
        Dict with 'path', 'bytes_written', 'created'.
    """
    file_path = Path(path)

    if not _is_path_safe_for_write(file_path):
        return {"error": f"Write blocked — path is in a protected system directory: {path}"}
    if not _is_path_allowed(file_path):
        return {"error": f"Write blocked — path is outside allowed roots: {path}"}

    try:
        existed = file_path.exists()

        if create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(content, encoding=encoding)

        return {
            "path": str(file_path),
            "bytes_written": len(content.encode(encoding)),
            "created": not existed,
        }
    except Exception as exc:
        return {"error": f"Failed to write {path}: {exc}"}


async def find_files(
    directory: str,
    pattern: str = "*",
    recursive: bool = True,
    max_results: int = 50,
    include_size: bool = True,
) -> dict[str, Any]:
    """
    Search for files matching a glob pattern.

    Args:
        directory:   Root directory to search.
        pattern:     Glob pattern (e.g. '*.py', '*.md').
        recursive:   Whether to search subdirectories.
        max_results: Maximum number of results to return.
        include_size: Whether to include file size info.

    Returns:
        Dict with 'directory', 'pattern', 'matches' list, 'total_found'.
    """
    root = Path(directory)
    if not _is_path_allowed(root):
        return {"error": f"Search blocked — path is outside allowed roots: {directory}"}
    if not root.exists() or not root.is_dir():
        return {"error": f"Directory not found: {directory}"}

    matches = []
    total = 0

    try:
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)

        for p in iterator:
            if not p.is_file():
                continue

            # Skip ignored directories
            try:
                rel = p.relative_to(root)
                if any(_should_skip_dir(part) for part in rel.parts[:-1]):
                    continue
            except ValueError:
                continue

            total += 1
            if len(matches) < max_results:
                entry: dict[str, Any] = {
                    "path": str(p),
                    "name": p.name,
                    "extension": p.suffix,
                }
                if include_size:
                    try:
                        stat = p.stat()
                        entry["size_bytes"] = stat.st_size
                        entry["modified"] = datetime.fromtimestamp(
                            stat.st_mtime
                        ).isoformat()
                    except OSError:
                        pass
                matches.append(entry)

        return {
            "directory": str(root),
            "pattern": pattern,
            "matches": matches,
            "total_found": total,
            "truncated": total > max_results,
        }
    except Exception as exc:
        return {"error": f"Search failed: {exc}"}


async def list_directory(
    path: str,
    show_hidden: bool = False,
    max_items: int = 100,
) -> dict[str, Any]:
    """
    List contents of a directory with metadata.

    Args:
        path:        Absolute path to the directory.
        show_hidden: Whether to include hidden files/dirs.
        max_items:   Maximum items to return.

    Returns:
        Dict with 'path', 'items' list, 'total_items'.
    """
    dir_path = Path(path)
    if not _is_path_allowed(dir_path):
        return {"error": f"List blocked — path is outside allowed roots: {path}"}
    if not dir_path.exists() or not dir_path.is_dir():
        return {"error": f"Directory not found: {path}"}

    items = []
    total = 0

    try:
        for entry in sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if not show_hidden and entry.name.startswith("."):
                continue
            if _should_skip_dir(entry.name) and entry.is_dir():
                continue

            total += 1
            if len(items) < max_items:
                item: dict[str, Any] = {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                }
                if entry.is_file():
                    try:
                        stat = entry.stat()
                        item["size_bytes"] = stat.st_size
                        item["modified"] = datetime.fromtimestamp(
                            stat.st_mtime
                        ).isoformat()
                    except OSError:
                        pass
                elif entry.is_dir():
                    try:
                        item["child_count"] = sum(
                            1 for _ in entry.iterdir()
                            if not _.name.startswith(".")
                        )
                    except PermissionError:
                        item["child_count"] = -1
                items.append(item)

        return {
            "path": str(dir_path),
            "items": items,
            "total_items": total,
        }
    except Exception as exc:
        return {"error": f"Failed to list directory: {exc}"}


async def file_info(path: str) -> dict[str, Any]:
    """
    Get detailed metadata about a file or directory.

    Returns:
        Dict with 'path', 'type', 'size_bytes', 'modified', 'extension', etc.
    """
    target = Path(path)
    if not _is_path_allowed(target):
        return {"error": f"Info blocked — path is outside allowed roots: {path}"}
    if not target.exists():
        return {"error": f"Path not found: {path}"}

    try:
        stat = target.stat()
        info: dict[str, Any] = {
            "path": str(target.resolve()),
            "name": target.name,
            "type": "directory" if target.is_dir() else "file",
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        }
        if target.is_file():
            info["extension"] = target.suffix
            info["size_human"] = _human_readable_size(stat.st_size)
        return info
    except Exception as exc:
        return {"error": f"Failed to get info: {exc}"}


def _human_readable_size(size: int) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size //= 1024
    return f"{size:.1f} TB"
