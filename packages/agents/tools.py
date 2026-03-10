"""
Agent Tools — callable tool functions for the agent orchestrator.

These wrap memory, document, file-system, git, and execution capabilities
into standalone async functions that agents can invoke during execution.

Tool categories:
  - Memory:    search_user_memories, search_documents
  - File I/O:  read_file, write_file, find_files, list_directory
  - Git:       git_status, git_log, git_diff, repo_summary
  - Execution: run_command, check_allowlist
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Memory Tools ─────────────────────────────────────────────────────


async def search_user_memories(
    query: str,
    user_id: str = "default",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Search Mem0 for user-related facts and preferences.

    Returns list of memory dicts with 'memory', 'id', 'score' fields.
    """
    try:
        from packages.memory.mem0_client import mem0_search
        results = mem0_search(query, user_id=user_id, limit=limit)
        return results
    except Exception as exc:
        logger.warning("Memory search failed: %s", exc)
        return []


async def search_documents(
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Search Qdrant for ingested document/code chunks.

    Returns list of dicts with 'content', 'metadata', 'score' fields.
    """
    try:
        from packages.memory.qdrant_store import search
        results = await search(query=query, k=k)
        # Filter for document content only
        return [
            r for r in results
            if r.get("metadata", {}).get("content_type") == "document"
            or r.get("metadata", {}).get("source_path")
        ]
    except Exception as exc:
        logger.warning("Document search failed: %s", exc)
        return []


# ── File System Tools ────────────────────────────────────────────────


async def read_file(
    path: str,
    max_lines: int | None = None,
) -> dict[str, Any]:
    """Read a file's contents (size-capped, safe)."""
    from packages.tools.fs import read_file as _read
    return await _read(path, max_lines=max_lines)


async def write_file(
    path: str,
    content: str,
) -> dict[str, Any]:
    """Write content to a file (blocks writes to protected system dirs)."""
    from packages.tools.fs import write_file as _write
    return await _write(path, content)


async def find_files(
    directory: str,
    pattern: str = "*",
    recursive: bool = True,
    max_results: int = 50,
) -> dict[str, Any]:
    """Search for files matching a glob pattern."""
    from packages.tools.fs import find_files as _find
    return await _find(directory, pattern=pattern, recursive=recursive, max_results=max_results)


async def list_directory(path: str) -> dict[str, Any]:
    """List contents of a directory with metadata."""
    from packages.tools.fs import list_directory as _ls
    return await _ls(path)


async def file_info(path: str) -> dict[str, Any]:
    """Get detailed metadata about a file or directory."""
    from packages.tools.fs import file_info as _info
    return await _info(path)


# ── Git / Repository Tools ───────────────────────────────────────────


async def git_status(repo_path: str) -> dict[str, Any]:
    """Get the working tree status of a git repository."""
    from packages.tools.repo import git_status as _status
    return await _status(repo_path)


async def git_log(
    repo_path: str,
    max_commits: int = 10,
) -> dict[str, Any]:
    """Get recent commit history."""
    from packages.tools.repo import git_log as _log
    return await _log(repo_path, max_commits=max_commits)


async def git_diff(
    repo_path: str,
    staged: bool = False,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Get the diff of changes in the working tree."""
    from packages.tools.repo import git_diff as _diff
    return await _diff(repo_path, staged=staged, file_path=file_path)


async def repo_summary(repo_path: str) -> dict[str, Any]:
    """Generate a high-level summary of a git repository."""
    from packages.tools.repo import repo_summary as _summary
    return await _summary(repo_path)


# ── Command Execution Tools ─────────────────────────────────────────


async def exec_command(
    command: str,
    cwd: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """
    Execute a shell command in a sandboxed subprocess.

    Pre-approved commands run immediately. Others return 'pending_approval'.
    """
    from packages.tools.exec import run_command
    return await run_command(command, cwd=cwd, timeout=timeout)


async def exec_approved_command(
    command: str,
    cwd: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Execute a user-approved command (bypasses the allowlist check)."""
    from packages.tools.exec import run_approved_command
    return await run_approved_command(command, cwd=cwd, timeout=timeout)


def check_command_safety(command: str) -> dict[str, Any]:
    """Check if a command is allowed, blocked, or requires approval."""
    from packages.tools.exec import check_allowlist
    return check_allowlist(command)


# ── Formatting ───────────────────────────────────────────────────────


async def format_tool_results(
    memories: list[dict],
    documents: list[dict],
) -> str:
    """Format tool results into a context string for the next agent."""
    parts = []

    if memories:
        lines = ["### User Memories"]
        for i, m in enumerate(memories, 1):
            text = m.get("memory", m.get("content", ""))
            if text:
                lines.append(f"  {i}. {text}")
        parts.append("\n".join(lines))

    if documents:
        lines = ["### Relevant Documents"]
        for i, d in enumerate(documents, 1):
            source = d.get("metadata", {}).get("source_path", "unknown")
            content = d.get("content", "")[:300]
            lines.append(f"  {i}. [{source}] {content}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts) if parts else "No relevant context found."


# ── Tool Registry ───────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    # Memory
    "search_user_memories": {
        "fn": search_user_memories,
        "category": "memory",
        "description": "Search for user-related facts/preferences in Mem0",
    },
    "search_documents": {
        "fn": search_documents,
        "category": "memory",
        "description": "Search for ingested documents/code in Qdrant",
    },
    # File System
    "read_file": {
        "fn": read_file,
        "category": "filesystem",
        "description": "Read the contents of a local file",
    },
    "write_file": {
        "fn": write_file,
        "category": "filesystem",
        "description": "Write content to a local file (safe)",
    },
    "find_files": {
        "fn": find_files,
        "category": "filesystem",
        "description": "Search for files matching a glob pattern",
    },
    "list_directory": {
        "fn": list_directory,
        "category": "filesystem",
        "description": "List contents of a directory",
    },
    "file_info": {
        "fn": file_info,
        "category": "filesystem",
        "description": "Get detailed metadata about a file or directory",
    },
    # Git
    "git_status": {
        "fn": git_status,
        "category": "git",
        "description": "Get working tree status of a git repo",
    },
    "git_log": {
        "fn": git_log,
        "category": "git",
        "description": "Get recent commit history",
    },
    "git_diff": {
        "fn": git_diff,
        "category": "git",
        "description": "Get diff of changes in working tree",
    },
    "repo_summary": {
        "fn": repo_summary,
        "category": "git",
        "description": "Generate a high-level summary of a git repository",
    },
    # Execution
    "exec_command": {
        "fn": exec_command,
        "category": "execution",
        "description": "Execute a shell command (sandboxed, requires allowlist or approval)",
    },
}


