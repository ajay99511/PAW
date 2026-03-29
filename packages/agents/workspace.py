"""
Workspace Configuration Manager

Manages workspace configurations for code agents with:
- Path-based permissions (read/write/execute)
- Dangerous path blocking
- Audit logging integration
- A2A capability advertisement

Configuration Location: ~/.personalassist/workspaces/<project_id>.json

Usage:
    from packages.agents.workspace import WorkspaceManager, WorkspaceConfig
    
    config = WorkspaceConfig(
        project_id="my-project",
        root="C:\\Agents\\PersonalAssist",
        permissions={
            "read": ["src/**/*", "tests/**/*"],
            "write": ["src/**/*"],
            "execute": False,
        }
    )
    
    manager = WorkspaceManager(config)
    if manager.can_read(Path("src/main.py")):
        content = Path("src/main.py").read_text()
"""

import fnmatch
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WorkspacePermissions(BaseModel):
    """Permissions for a workspace."""
    
    read: list[str] = Field(
        default=["**/*"],
        description="Glob patterns for readable paths",
    )
    write: list[str] = Field(
        default=[],
        description="Glob patterns for writable paths",
    )
    execute: bool = Field(
        default=False,
        description="Whether command execution is allowed",
    )
    git_operations: bool = Field(
        default=True,
        description="Whether Git operations are allowed",
    )
    network_access: bool = Field(
        default=False,
        description="Whether network access is allowed (for web search, etc.)",
    )


class WorkspaceConfig(BaseModel):
    """Configuration for a workspace."""
    
    project_id: str = Field(..., description="Unique project identifier")
    root: Path = Field(..., description="Root directory of the workspace")
    permissions: WorkspacePermissions = Field(..., description="Workspace permissions")
    context_collection: str = Field(
        default="",
        description="Qdrant collection name for project-specific context",
    )
    agent_instructions: str = Field(
        default="",
        description="Custom instructions for agents working in this workspace",
    )
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    model_config = {"arbitrary_types_allowed": True}


class WorkspaceManager:
    """
    Manages workspace with permission enforcement and audit logging.
    """
    
    # Dangerous paths that are always blocked (Windows-specific)
    DANGEROUS_PATTERNS = [
        # Windows system directories
        'C:/Windows/**',
        'C:/Windows/*',
        'C:/$Recycle.Bin/**',
        'C:/System Volume Information/**',
        'C:/Program Files/**',
        'C:/Program Files (x86)/**',
        
        # Sensitive user data
        '**/.ssh/**',
        '**/.aws/**',
        '**/.azure/**',
        '**/.git-credentials',
        '**/.git-credentials.*',
        '**/.netrc',
        '**/.npmrc',
        '**/.pypirc',
        
        # Environment and secrets
        '**/.env',
        '**/.env.*',
        '**/*secret*',
        '**/*password*',
        '**/*credential*',
        '**/.vault_pass*',
        
        # Browser data
        '**/AppData/**/Chrome/**',
        '**/AppData/**/Firefox/**',
        '**/Application Data/**/Chrome/**',
        
        # System files
        '**/pagefile.sys',
        '**/hiberfil.sys',
        '**/swapfile.sys',
    ]

    DANGEROUS_PREFIXES = [
        "c:/windows",
        "c:/$recycle.bin",
        "c:/system volume information",
        "c:/program files",
        "c:/program files (x86)",
    ]
    
    def __init__(self, config: WorkspaceConfig):
        """
        Initialize workspace manager.
        
        Args:
            config: Workspace configuration
        """
        self.config = config
        self.audit_log = self.config.root / '.agent_audit.log'
        
        # Ensure audit log file exists
        try:
            self.audit_log.parent.mkdir(parents=True, exist_ok=True)
            if not self.audit_log.exists():
                self.audit_log.touch()
        except Exception as exc:
            logger.warning(f"Could not create audit log: {exc}")
    
    def _is_path_safe(self, path: Path) -> tuple[bool, str]:
        """
        Check if a path is safe to access (not dangerous).
        
        Args:
            path: Path to check
        
        Returns:
            Tuple of (is_safe, reason)
        """
        try:
            # Resolve to absolute path
            resolved_path = path.resolve()
            path_str = str(resolved_path).replace('\\', '/')
            normalized = path_str.lower().rstrip("/")
            root_resolved = self.config.root.resolve()
            root_str = str(root_resolved).replace("\\", "/").lower().rstrip("/")

            # Explicit prefix checks for critical Windows/system paths.
            for prefix in self.DANGEROUS_PREFIXES:
                if normalized == prefix or normalized.startswith(prefix + "/"):
                    return False, f"Matches dangerous path prefix: {prefix}"

            # Explicit checks for high-value secret locations.
            sensitive_markers = ["/.ssh/", "/.aws/", "/.azure/", "/.env"]
            for marker in sensitive_markers:
                if marker in normalized or normalized.endswith(marker.rstrip("/")):
                    return False, f"Matches dangerous path marker: {marker}"
            
            # Check against dangerous patterns
            for pattern in self.DANGEROUS_PATTERNS:
                if fnmatch.fnmatch(path_str, pattern):
                    return False, f"Matches dangerous pattern: {pattern}"
            
            # Check for path traversal attempts
            if '..' in str(path):
                return False, "Path traversal detected"
            
            # Enforce workspace root boundary for both relative and absolute paths.
            try:
                resolved_path.relative_to(root_resolved)
            except ValueError:
                # If neither dangerous nor in-root, deny as outside root.
                return False, "Path outside workspace root"
            
            return True, "Safe"
        
        except Exception as exc:
            return False, f"Error checking path: {exc}"
    
    def _matches_pattern(self, path: Path, patterns: list[str]) -> bool:
        """
        Check if path matches any of the given glob patterns.
        
        Args:
            path: Path to check
            patterns: List of glob patterns
        
        Returns:
            True if path matches any pattern
        """
        try:
            # Get relative path from root
            if path.is_absolute():
                try:
                    rel_path = path.resolve().relative_to(self.config.root.resolve())
                except ValueError:
                    return False
            else:
                rel_path = path
            
            path_str = str(rel_path).replace('\\', '/')
            
            for pattern in patterns:
                normalized_pattern = pattern.replace("\\", "/")

                if fnmatch.fnmatch(path_str, normalized_pattern):
                    return True
                if Path(path_str).match(normalized_pattern):
                    return True

                # Support common "src/**/*" intent for files directly under "src/".
                if "/**/*" in normalized_pattern:
                    alt_patterns = [
                        normalized_pattern.replace("/**/*", "/**"),
                        normalized_pattern.replace("/**/*", "/*"),
                    ]
                    if any(
                        fnmatch.fnmatch(path_str, alt) or Path(path_str).match(alt)
                        for alt in alt_patterns
                    ):
                        return True

                # Also allow exact file match for strict patterns.
                if normalized_pattern.rstrip("/") == path_str:
                    return True
            
            return False
        
        except Exception:
            return False
    
    def can_read(self, path: Path) -> tuple[bool, str]:
        """
        Check if reading from a path is allowed.
        
        Args:
            path: Path to check
        
        Returns:
            Tuple of (allowed, reason)
        """
        # Check if path is safe
        is_safe, safety_reason = self._is_path_safe(path)
        if not is_safe:
            self._audit('read', path, False, safety_reason)
            return False, safety_reason
        
        # Check read allowlist
        if self._matches_pattern(path, self.config.permissions.read):
            self._audit('read', path, True, "Matches read allowlist")
            return True, "Matches read allowlist"
        
        reason = "Path not in read allowlist"
        self._audit('read', path, False, reason)
        return False, reason
    
    def can_write(self, path: Path) -> tuple[bool, str]:
        """
        Check if writing to a path is allowed.
        
        Args:
            path: Path to check
        
        Returns:
            Tuple of (allowed, reason)
        """
        # Check if path is safe
        is_safe, safety_reason = self._is_path_safe(path)
        if not is_safe:
            self._audit('write', path, False, safety_reason)
            return False, safety_reason
        
        # Check write allowlist
        if self._matches_pattern(path, self.config.permissions.write):
            self._audit('write', path, True, "Matches write allowlist")
            return True, "Matches write allowlist"
        
        reason = "Path not in write allowlist"
        self._audit('write', path, False, reason)
        return False, reason
    
    def can_execute(self, command: str) -> tuple[bool, str]:
        """
        Check if command execution is allowed.
        
        Args:
            command: Command to check
        
        Returns:
            Tuple of (allowed, reason)
        """
        if not self.config.permissions.execute:
            reason = "Execution not allowed for this workspace"
            self._audit('execute', command, False, reason)
            return False, reason
        
        # Check for dangerous commands
        dangerous_commands = [
            'del', 'erase', 'rmdir', 'rd',
            'format', 'chkdsk', 'diskpart',
            'shutdown', 'logoff', 'taskkill',
            'net user', 'net localgroup',
            'reg delete', 'reg add',
        ]
        
        command_lower = command.lower()
        for dangerous in dangerous_commands:
            if dangerous in command_lower:
                reason = f"Dangerous command detected: {dangerous}"
                self._audit('execute', command, False, reason)
                return False, reason
        
        self._audit('execute', command, True, "Command allowed")
        return True, "Allowed"
    
    def can_perform_git_operation(self, operation: str) -> tuple[bool, str]:
        """
        Check if a Git operation is allowed.
        
        Args:
            operation: Git operation (e.g., 'status', 'commit', 'push')
        
        Returns:
            Tuple of (allowed, reason)
        """
        if not self.config.permissions.git_operations:
            reason = "Git operations not allowed for this workspace"
            self._audit('git', operation, False, reason)
            return False, reason
        
        # Check for dangerous Git operations
        dangerous_ops = ['filter-branch', 'update-ref -d']
        for dangerous in dangerous_ops:
            if dangerous in operation.lower():
                reason = f"Dangerous Git operation: {dangerous}"
                self._audit('git', operation, False, reason)
                return False, reason
        
        self._audit('git', operation, True, "Git operation allowed")
        return True, "Allowed"
    
    def _audit(self, action: str, target: Any, allowed: bool, reason: str) -> None:
        """
        Log an audit entry.
        
        Args:
            action: Action type (read/write/execute/git)
            target: Target path or command
            allowed: Whether action was allowed
            reason: Reason for decision
        """
        entry = {
            'timestamp': datetime.now().isoformat(),
            'project_id': self.config.project_id,
            'action': action,
            'target': str(target),
            'allowed': allowed,
            'reason': reason,
        }
        
        try:
            with open(self.audit_log, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as exc:
            logger.error(f"Failed to write audit log: {exc}")
    
    def get_audit_log(self, limit: int = 100) -> list[dict]:
        """
        Get recent audit log entries.
        
        Args:
            limit: Maximum number of entries to return
        
        Returns:
            List of audit log entries
        """
        entries = []
        
        try:
            with open(self.audit_log, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        entries.append(json.loads(line))
        except Exception as exc:
            logger.error(f"Failed to read audit log: {exc}")
            return []
        
        # Return most recent entries
        return entries[-limit:] if len(entries) > limit else entries
    
    def get_stats(self) -> dict[str, Any]:
        """
        Get workspace statistics.
        
        Returns:
            Dict with workspace statistics
        """
        audit_entries = self.get_audit_log()
        
        # Count by action
        action_counts = {}
        allowed_counts = {'allowed': 0, 'denied': 0}
        
        for entry in audit_entries:
            action = entry.get('action', 'unknown')
            action_counts[action] = action_counts.get(action, 0) + 1
            
            if entry.get('allowed'):
                allowed_counts['allowed'] += 1
            else:
                allowed_counts['denied'] += 1
        
        return {
            'project_id': self.config.project_id,
            'root': str(self.config.root),
            'audit_entries': len(audit_entries),
            'action_counts': action_counts,
            'allowed_counts': allowed_counts,
            'permissions': self.config.permissions.model_dump(),
        }


def get_workspace_dir() -> Path:
    """Get the workspace configuration directory."""
    workspace_dir = Path.home() / ".personalassist" / "workspaces"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir


def load_workspace_config(project_id: str) -> WorkspaceConfig | None:
    """
    Load workspace configuration for a project.
    
    Args:
        project_id: Project identifier
    
    Returns:
        WorkspaceConfig or None if not found
    """
    workspace_dir = get_workspace_dir()
    config_file = workspace_dir / f"{project_id}.json"
    
    if not config_file.exists():
        return None
    
    try:
        content = config_file.read_text(encoding='utf-8')
        data = json.loads(content)
        return WorkspaceConfig(**data)
    except Exception as exc:
        logger.error(f"Failed to load workspace config: {exc}")
        return None


def save_workspace_config(config: WorkspaceConfig) -> Path:
    """
    Save workspace configuration.
    
    Args:
        config: Workspace configuration
    
    Returns:
        Path to saved config file
    """
    workspace_dir = get_workspace_dir()
    config_file = workspace_dir / f"{config.project_id}.json"
    
    # Update timestamp
    config.updated_at = datetime.now().isoformat()
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config.model_dump(mode='json'), f, indent=2)
        
        logger.info(f"Saved workspace config: {config_file}")
        return config_file
    
    except Exception as exc:
        logger.error(f"Failed to save workspace config: {exc}")
        raise


def list_workspace_configs() -> list[WorkspaceConfig]:
    """
    List all workspace configurations.
    
    Returns:
        List of WorkspaceConfig objects
    """
    workspace_dir = get_workspace_dir()
    configs = []
    
    for config_file in workspace_dir.glob("*.json"):
        try:
            content = config_file.read_text(encoding='utf-8')
            data = json.loads(content)
            configs.append(WorkspaceConfig(**data))
        except Exception as exc:
            logger.warning(f"Failed to load config {config_file}: {exc}")
    
    return configs


def create_default_workspace(project_root: Path) -> WorkspaceConfig:
    """
    Create a default workspace configuration.
    
    Args:
        project_root: Root directory of the project
    
    Returns:
        WorkspaceConfig with sensible defaults
    """
    project_id = project_root.name.lower().replace(' ', '-').replace('_', '-')
    
    config = WorkspaceConfig(
        project_id=project_id,
        root=project_root,
        permissions=WorkspacePermissions(
            read=["**/*"],  # Read all files
            write=["src/**/*", "tests/**/*", "docs/**/*"],  # Write to common dirs
            execute=False,  # No execution by default
            git_operations=True,  # Git operations allowed
            network_access=False,  # No network access
        ),
        context_collection=f"project_{project_id}",
        agent_instructions="Focus on code quality and follow best practices.",
    )
    
    save_workspace_config(config)
    return config
