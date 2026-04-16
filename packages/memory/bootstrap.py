"""
Bootstrap File Manager (Layer 1 of 5-Layer Memory System)

Manages static bootstrap files that are injected into every system prompt.
These files provide operating instructions, persona, user preferences, and tool definitions.

Bootstrap Files:
- AGENTS.md: Operating instructions, standing orders
- SOUL.md: Persona, tone, boundaries
- USER.md: Who the user is, preferences
- IDENTITY.md: Agent name and vibe
- TOOLS.md: Local tool notes, capabilities
- HEARTBEAT.md: Periodic checklist for background tasks
- MEMORY.md: Curated long-term memory (main session only)

Usage:
    from packages.memory.bootstrap import load_bootstrap_files
    
    # Load all bootstrap files for main agent
    context = await load_bootstrap_files(agent_type="main")
    
    # Load limited bootstrap for sub-agents
    context = await load_bootstrap_files(agent_type="sub-agent")
"""

import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Bootstrap file definitions
BOOTSTRAP_FILES = [
    "AGENTS.md",
    "SOUL.md",
    "USER.md",
    "IDENTITY.md",
    "TOOLS.md",
    "HEARTBEAT.md",
    "MEMORY.md",
]

# Sub-agents only get these files (limited context)
SUB_AGENT_FILES = [
    "AGENTS.md",
    "TOOLS.md",
]

# Character limits
MAX_CHARS_PER_FILE = 20_000
MAX_TOTAL_CHARS = 150_000
TRUNCATION_MARKER = "\n\n[... content truncated to stay within token budget ...]"


def get_bootstrap_dir() -> Path:
    """Get the bootstrap files directory (~/.personalassist/)."""
    return Path.home() / ".personalassist"


async def load_bootstrap_files(
    agent_type: Literal["main", "sub-agent"] = "main",
    exclude_files: list[str] | None = None,
) -> str:
    """
    Load bootstrap files from ~/.personalassist/ and format for system prompt injection.
    
    Args:
        agent_type: "main" for full bootstrap, "sub-agent" for limited context
        exclude_files: Optional list of files to exclude (e.g., MEMORY.md for group sessions)
    
    Returns:
        Formatted bootstrap context string, or empty string if no files found
    """
    base_path = get_bootstrap_dir()
    
    # Determine which files to load
    if agent_type == "sub-agent":
        files_to_load = SUB_AGENT_FILES
    else:
        files_to_load = BOOTSTRAP_FILES
    
    # Apply exclusions
    if exclude_files:
        files_to_load = [f for f in files_to_load if f not in exclude_files]
    
    sections = []
    total_chars = 0
    
    for filename in files_to_load:
        file_path = base_path / filename
        
        # Skip if file doesn't exist
        if not file_path.exists():
            logger.debug(f"Bootstrap file not found: {filename}")
            continue
        
        try:
            content = file_path.read_text(encoding='utf-8')
            
            # Skip empty files
            if not content.strip():
                continue
            
            # Truncate to per-file limit
            if len(content) > MAX_CHARS_PER_FILE:
                content = content[:MAX_CHARS_PER_FILE]
                content += TRUNCATION_MARKER
            
            # Check total budget
            if total_chars + len(content) > MAX_TOTAL_CHARS:
                remaining = MAX_TOTAL_CHARS - total_chars
                if remaining > 100:  # Only add if there's meaningful space
                    content = content[:remaining]
                    content += TRUNCATION_MARKER
                    sections.append(f"## {filename.replace('.md', '')}\n{content}")
                break
            
            # Add to sections
            sections.append(f"## {filename.replace('.md', '')}\n{content}")
            total_chars += len(content)
            
            logger.debug(f"Loaded bootstrap file: {filename} ({len(content)} chars)")
        
        except Exception as exc:
            logger.warning(f"Failed to load bootstrap file {filename}: {exc}")
            continue
    
    if not sections:
        logger.info("No bootstrap files loaded")
        return ""
    
    result = "\n\n".join(sections)
    logger.info(f"Loaded {len(sections)} bootstrap files ({len(result)} chars total)")
    
    return result


def create_bootstrap_templates(overwrite: bool = False) -> dict[str, Path]:
    """
    Create bootstrap file templates if they don't exist.
    
    Args:
        overwrite: If True, overwrite existing files (default: False)
    
    Returns:
        Dict of filename -> path for all bootstrap files
    """
    base_path = get_bootstrap_dir()
    base_path.mkdir(parents=True, exist_ok=True)
    
    templates = {
        "AGENTS.md": """# Agent Operating Instructions

## Primary Directive
You are a helpful, harmless, and honest AI assistant. Your goal is to assist the user effectively while maintaining safety and ethical standards.

## Standing Orders
1. **Be proactive**: If you notice potential issues or improvements, mention them
2. **Show your work**: Explain your reasoning when solving complex problems
3. **Cite sources**: When using document content, cite the source path in brackets
4. **Ask for clarification**: If a request is ambiguous, ask before proceeding
5. **Respect boundaries**: Stay within your configured permissions

## Response Style
- Be concise but thorough
- Use markdown formatting for clarity
- Include actionable next steps
- Admit uncertainty when present

## Safety Guidelines
- Never execute commands that could harm the system
- Never expose sensitive information (API keys, passwords, etc.)
- Respect user privacy and data sovereignty
""",
        
        "SOUL.md": """# Agent Persona & Tone

## Personality
- **Helpful**: Genuinely want to assist the user
- **Professional**: Maintain a professional but friendly tone
- **Curious**: Ask questions to better understand user needs
- **Humble**: Acknowledge limitations and uncertainties

## Communication Style
- Clear and direct, but not blunt
- Technical when appropriate, accessible when needed
- Patient with repeated questions
- Enthusiastic about user's successes

## Boundaries
- Do not engage in harmful or unethical activities
- Do not pretend to have capabilities you don't have
- Do not make promises about future performance
- Do not share personal opinions on sensitive topics

## Relationship with User
- You are an assistant, not a peer
- Respect the user's expertise and decisions
- Offer suggestions, but defer to user judgment
- Build trust through consistent, reliable assistance
""",
        
        "USER.md": """# User Profile

## Basic Information
- **Name**: [Your Name]
- **Location**: [Your Location/Timezone]
- **Occupation**: [Your Role/Profession]

## Technical Preferences
- **Primary Languages**: Python, TypeScript
- **Preferred Tools**: VS Code, Git, Docker
- **Development Style**: Test-driven, documentation-focused

## Communication Preferences
- **Detail Level**: Prefer concise summaries with option to expand
- **Format**: Markdown with code blocks for technical content
- **Notifications**: Only for important updates

## Project Context
- Currently working on: PersonalAssist AI system
- Tech stack: FastAPI, Tauri, React, Qdrant, local memory extractor
- Goals: Build a production-grade local AI assistant

## Important Notes
- Values privacy and local-first architecture
- Prefers open-source solutions when possible
- Interested in performance optimization
""",
        
        "IDENTITY.md": """# Agent Identity

## Name
PersonalAssist

## Version
0.2.0

## Role
Local-first AI assistant with long-term memory and agentic capabilities

## Capabilities
- Natural language conversation
- Document and code RAG (Retrieval-Augmented Generation)
- Multi-agent orchestration (Planner → Researcher → Synthesizer)
- Background task execution (scheduled jobs)
- File system operations (read/write with permissions)
- Git operations (status, log, diff, commit)
- Web search and research

## Limitations
- Requires user permission for mutating operations
- Cannot access external networks without explicit approval
- Context window limits (managed via compaction)
- Local execution only (no cloud processing of sensitive data)

## Mission
To be a reliable, intelligent, and trustworthy assistant that helps users accomplish more while respecting their privacy and preferences.
""",
        
        "TOOLS.md": """# Available Tools

## File System Tools
- `fs_read`: Read file contents
- `fs_write`: Write/create files
- `fs_list`: List directory contents
- `fs_search`: Search files by pattern

## Git Tools
- `git_status`: Show repository status
- `git_log`: Show commit history
- `git_diff`: Show changes
- `git_commit`: Create commits (with permission)

## Code Tools
- `code_review`: Review code for issues
- `test_generate`: Generate test cases
- `dependency_audit`: Check for outdated/vulnerable dependencies

## Memory Tools
- `memory_search`: Search long-term memories
- `memory_get`: Retrieve specific memories
- `memory_store`: Store new memories

## Web Tools
- `web_search`: Search the internet
- `web_fetch`: Fetch and parse web pages

## Execution Tools
- `exec`: Run shell commands (requires explicit permission)
- `process`: Run and manage long-running processes

## Tool Usage Rules
1. Read-only tools can be used freely
2. Write/exec tools require user permission
3. Always show planned changes before executing
4. Log all tool calls for audit purposes
""",
        
        "HEARTBEAT.md": """# Heartbeat Checklist

## Daily Checks (8:00 AM)
- [ ] Review overnight activity summary
- [ ] Check for pending background tasks
- [ ] Verify system health (Qdrant, Redis, Ollama)
- [ ] Review any alerts or errors from cron jobs

## Weekly Checks (Monday 9:00 AM)
- [ ] Review weekly activity summary
- [ ] Check memory consolidation status
- [ ] Verify backup snapshots are current
- [ ] Review audit logs for anomalies

## Monthly Checks (1st of month)
- [ ] Review monthly usage statistics
- [ ] Check for outdated dependencies
- [ ] Review and clean up old memories
- [ ] Verify disaster recovery procedures

## Proactive Monitoring
- Monitor for repeated errors
- Track memory growth rate
- Watch for performance degradation
- Alert on unusual patterns

## Response Procedures
1. **Error detected**: Log details, attempt recovery, notify user if persistent
2. **Performance issue**: Check resource usage, restart services if needed
3. **Memory full**: Trigger compaction, archive old sessions
4. **Service down**: Attempt restart, escalate if fails
""",
        
        "MEMORY.md": """# Long-Term Memory (Curated)

This file contains curated long-term memories that have been manually reviewed and deemed important for persistent retention.

## Format
Memories are organized by category and include:
- **Date**: When the memory was recorded
- **Category**: Type of memory (decision, preference, fact, etc.)
- **Content**: The actual memory content
- **Context**: Related projects, conversations, or events

## Categories
- **Decisions**: Important choices and their rationales
- **Preferences**: User preferences and working styles
- **Facts**: Stable facts about user, projects, or environment
- **Relationships**: Important people, organizations, connections
- **Goals**: Long-term objectives and progress

## Usage
- These memories are injected into every conversation
- Update when significant decisions or discoveries are made
- Review periodically for accuracy and relevance

---

*This file is auto-managed by the memory consolidation system.*
*Last updated: [Auto-populated]*
""",
    }
    
    created = {}
    
    for filename, content in templates.items():
        file_path = base_path / filename
        
        if file_path.exists() and not overwrite:
            logger.debug(f"Bootstrap file already exists: {filename}")
            created[filename] = file_path
            continue
        
        file_path.write_text(content, encoding='utf-8')
        logger.info(f"Created bootstrap template: {filename}")
        created[filename] = file_path
    
    return created


async def get_bootstrap_summary() -> dict:
    """
    Get a summary of loaded bootstrap files.
    
    Returns:
        Dict with file names, sizes, and load status
    """
    base_path = get_bootstrap_dir()
    summary = {
        "directory": str(base_path),
        "files": {},
        "total_chars": 0,
        "total_files": 0,
    }
    
    for filename in BOOTSTRAP_FILES:
        file_path = base_path / filename
        if file_path.exists():
            try:
                content = file_path.read_text(encoding='utf-8')
                summary["files"][filename] = {
                    "exists": True,
                    "chars": len(content),
                    "lines": len(content.splitlines()),
                }
                summary["total_chars"] += len(content)
                summary["total_files"] += 1
            except Exception as exc:
                summary["files"][filename] = {
                    "exists": True,
                    "error": str(exc),
                }
        else:
            summary["files"][filename] = {
                "exists": False,
            }
    
    return summary
