"""
Sandboxed Command Execution — safe shell command runner for agents.

Security model:
  - Commands run in a subprocess with a strict timeout
  - Output is size-capped to prevent memory issues
  - A configurable allowlist defines which commands are pre-approved
  - Non-allowlisted commands return a "pending_approval" status,
    which the UI should intercept and prompt the user for confirmation

Usage:
    from packages.tools.exec import run_command, check_allowlist
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from typing import Any

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

# Default timeout for command execution (seconds)
DEFAULT_TIMEOUT = 30

# Maximum output size (512 KB)
MAX_OUTPUT_SIZE = 512 * 1024

# Commands that are pre-approved (read-only / informational)
# These can be run without explicit user approval.
ALLOWED_COMMANDS = {
    # Python
    "python --version",
    "python -m pytest",
    "pip list",
    "pip show",

    # Node.js
    "node --version",
    "npm --version",
    "npm list",
    "npm run build",
    "npm run test",
    "npm run lint",
    "npx tsc --noEmit",

    # Git (read-only)
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git remote -v",
    "git rev-parse HEAD",

    # System info
    "whoami",
    "hostname",
    "dir",
    "ls",
    "pwd",
    "echo",
    "cat",
    "type",
    "where",
    "which",

    # Docker (read-only)
    "docker ps",
    "docker images",
    "docker compose ps",

    # Rust
    "rustc --version",
    "cargo --version",
}

# Patterns that are never allowed (even with approval)
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",                 # rm -rf /
    r"del\s+/s\s+/q\s+C:\\",         # del /s /q C:\
    r"format\s+[A-Z]:",              # format C:
    r"shutdown",                      # shutdown
    r"mkfs",                          # mkfs
    r"dd\s+if=",                      # dd if=
    r">\s*/dev/sd",                   # redirect to disk device
    r"reg\s+delete",                  # registry delete
]

# Shell control operators that allow command chaining/injection.
# We block these and allow only single-command execution.
_SHELL_CONTROL_PATTERN = re.compile(r"[;&|`><]")


# ── Safety ───────────────────────────────────────────────────────────


def _contains_shell_controls(command: str) -> bool:
    """Return True when command contains shell control operators."""
    return bool(_SHELL_CONTROL_PATTERN.search(command))


def _split_command(command: str) -> list[str]:
    """Best-effort command splitter for allowlist checks."""
    try:
        return shlex.split(command, posix=False)
    except Exception:
        return command.strip().split()


def _is_command_allowed(command: str) -> bool:
    """Check if a command is in the pre-approved allowlist."""
    cmd = command.strip()
    if not cmd or _contains_shell_controls(cmd):
        return False

    tokens = _split_command(cmd)
    if not tokens:
        return False

    canonical = " ".join(tokens).lower()
    allowed_canonical = {
        " ".join(_split_command(allowed)).lower()
        for allowed in ALLOWED_COMMANDS
    }
    if canonical in allowed_canonical:
        return True

    head = tokens[0].lower()

    # Safe flexible form: `echo <text>`
    if head == "echo" and len(tokens) >= 1:
        return True

    # Safe flexible form: `pip show <package-name>`
    if (
        head == "pip"
        and len(tokens) == 3
        and tokens[1].lower() == "show"
        and re.fullmatch(r"[A-Za-z0-9_.-]+", tokens[2]) is not None
    ):
        return True

    return False


def _is_command_blocked(command: str) -> bool:
    """Check if a command matches any blocked patterns."""
    if _contains_shell_controls(command):
        return True

    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def check_allowlist(command: str) -> dict[str, Any]:
    """
    Check the safety status of a command before execution.

    Returns:
        Dict with 'command', 'allowed', 'blocked', 'requires_approval'.
    """
    blocked = _is_command_blocked(command)
    allowed = _is_command_allowed(command) and not blocked

    return {
        "command": command,
        "allowed": allowed,
        "blocked": blocked,
        "requires_approval": not allowed and not blocked,
    }


# ── Public API ───────────────────────────────────────────────────────


async def run_command(
    command: str,
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    force_approve: bool = False,
) -> dict[str, Any]:
    """
    Execute a shell command in a sandboxed subprocess.

    Args:
        command:       The command string to execute.
        cwd:           Working directory (defaults to current).
        timeout:       Maximum execution time in seconds.
        force_approve: If True, skip the allowlist check (user-approved).

    Returns:
        Dict with 'stdout', 'stderr', 'returncode', 'success', 'timed_out'.
        Or 'pending_approval' status if the command requires user consent.
    """
    # Safety checks
    if _is_command_blocked(command):
        return {
            "error": "Command is blocked for safety reasons",
            "command": command,
            "blocked": True,
            "success": False,
        }

    if not force_approve and not _is_command_allowed(command):
        return {
            "status": "pending_approval",
            "command": command,
            "message": "This command requires user approval before execution.",
            "success": False,
        }

    logger.info("Executing command: %s (cwd=%s, timeout=%ds)", command, cwd, timeout)

    try:
        # Use shell=True on Windows for proper command interpretation.
        # Safety is enforced by allowlist + blocked-pattern checks above.
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "command": command,
                "error": f"Command timed out after {timeout}s",
                "timed_out": True,
                "success": False,
            }

        out = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_SIZE]
        err = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_SIZE]

        result = {
            "command": command,
            "stdout": out,
            "stderr": err,
            "returncode": proc.returncode,
            "success": proc.returncode == 0,
            "timed_out": False,
        }

        logger.info(
            "Command finished: rc=%d, stdout=%d bytes, stderr=%d bytes",
            proc.returncode, len(out), len(err),
        )

        return result

    except Exception as exc:
        logger.error("Command execution failed: %s", exc)
        return {
            "command": command,
            "error": f"Execution failed: {exc}",
            "success": False,
        }


async def run_approved_command(
    command: str,
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    Execute a user-approved command (bypasses allowlist check).

    This should only be called after explicit user confirmation via the UI.
    """
    return await run_command(command, cwd=cwd, timeout=timeout, force_approve=True)


