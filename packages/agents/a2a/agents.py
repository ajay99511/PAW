"""
Tier 1 Agent Cards

Pre-defined agent cards for Tier 1 (Full A2A) agents.
These agents benefit from capability discovery and async task delegation.

Tier 1 Agents:
- Code Reviewer
- Workspace Analyzer
- Test Generator
- Dependency Auditor

Usage:
    from packages.agents.a2a.agents import register_tier1_agents
    
    register_tier1_agents()
"""

import json
import logging
import re
from typing import Any

from packages.agents.a2a.registry import register_agent
from packages.agents.crew import run_crew

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Agent Card Definitions
# ─────────────────────────────────────────────────────────────────────────────

CODE_REVIEWER_CARD = {
    "agent_id": "code-reviewer",
    "name": "Code Review Agent",
    "description": "Reviews code for security vulnerabilities, performance issues, and style problems",
    "capabilities": ["code_review", "security_scan", "style_check", "best_practices"],
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to file or directory to review",
            },
            "focus": {
                "type": "string",
                "enum": ["security", "performance", "style", "all"],
                "default": "all",
                "description": "Focus area for the review",
            },
            "max_issues": {
                "type": "integer",
                "default": 20,
                "description": "Maximum number of issues to report",
            },
        },
        "required": ["path"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "line": {"type": "integer"},
                        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                        "category": {"type": "string"},
                        "message": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                },
            },
            "summary": {"type": "string"},
            "score": {
                "type": "object",
                "properties": {
                    "security": {"type": "integer"},
                    "performance": {"type": "integer"},
                    "style": {"type": "integer"},
                    "overall": {"type": "integer"},
                },
            },
        },
    },
    "permissions": {
        "read": ["src/**/*", "lib/**/*", "app/**/*", "packages/**/*"],
        "write": [],
        "execute": False,
    },
}

WORKSPACE_ANALYZER_CARD = {
    "agent_id": "workspace-analyzer",
    "name": "Workspace Analysis Agent",
    "description": "Analyzes project structure, dependencies, and codebase health",
    "capabilities": ["workspace_analysis", "dependency_audit", "structure_review", "tech_stack_detection"],
    "input_schema": {
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to project root",
            },
            "depth": {
                "type": "integer",
                "default": 3,
                "description": "Directory depth to analyze",
            },
            "include_hidden": {
                "type": "boolean",
                "default": False,
                "description": "Include hidden directories (.git, .venv, etc.)",
            },
        },
        "required": ["project_path"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "structure": {
                "type": "object",
                "description": "Directory structure overview",
            },
            "dependencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "version": {"type": "string"},
                        "type": {"type": "string"},
                    },
                },
            },
            "tech_stack": {
                "type": "array",
                "items": {"type": "string"},
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
            },
            "metrics": {
                "type": "object",
                "properties": {
                    "total_files": {"type": "integer"},
                    "total_dirs": {"type": "integer"},
                    "code_files": {"type": "integer"},
                    "config_files": {"type": "integer"},
                    "docs_files": {"type": "integer"},
                },
            },
        },
    },
    "permissions": {
        "read": ["**/*"],
        "write": [],
        "execute": True,  # Needs execute for some analysis commands
    },
}

TEST_GENERATOR_CARD = {
    "agent_id": "test-generator",
    "name": "Test Generation Agent",
    "description": "Generates test cases for functions and classes",
    "capabilities": ["test_generation", "test_coverage", "mock_generation", "fixture_creation"],
    "input_schema": {
        "type": "object",
        "properties": {
            "source_path": {
                "type": "string",
                "description": "Path to source file or directory",
            },
            "test_framework": {
                "type": "string",
                "enum": ["pytest", "unittest", "jest", "mocha"],
                "default": "pytest",
                "description": "Test framework to use",
            },
            "coverage_target": {
                "type": "integer",
                "default": 80,
                "description": "Target code coverage percentage",
            },
            "include_integration": {
                "type": "boolean",
                "default": False,
                "description": "Include integration tests",
            },
        },
        "required": ["source_path"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "tests_generated": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "function": {"type": "string"},
                        "test_name": {"type": "string"},
                        "coverage": {"type": "string"},
                    },
                },
            },
            "coverage_estimate": {"type": "number"},
            "files_created": {"type": "array", "items": {"type": "string"}},
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
    },
    "permissions": {
        "read": ["src/**/*", "lib/**/*", "app/**/*"],
        "write": ["tests/**/*", "test/**/*"],
        "execute": True,  # To run tests and check coverage
    },
}

DEPENDENCY_AUDITOR_CARD = {
    "agent_id": "dependency-auditor",
    "name": "Dependency Audit Agent",
    "description": "Checks for outdated, vulnerable, or unused dependencies",
    "capabilities": ["dependency_audit", "security_scan", "version_check", "unused_detection"],
    "input_schema": {
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Path to project root",
            },
            "check_outdated": {
                "type": "boolean",
                "default": True,
                "description": "Check for outdated packages",
            },
            "check_vulnerabilities": {
                "type": "boolean",
                "default": True,
                "description": "Check for security vulnerabilities",
            },
            "check_unused": {
                "type": "boolean",
                "default": False,
                "description": "Check for unused dependencies",
            },
        },
        "required": ["project_path"],
    },
    "output_schema": {
        "type": "object",
        "properties": {
            "outdated": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "current": {"type": "string"},
                        "latest": {"type": "string"},
                        "severity": {"type": "string"},
                    },
                },
            },
            "vulnerabilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "version": {"type": "string"},
                        "cve": {"type": "string"},
                        "severity": {"type": "string"},
                        "fixed_in": {"type": "string"},
                    },
                },
            },
            "unused": {
                "type": "array",
                "items": {"type": "string"},
            },
            "recommendations": {"type": "array", "items": {"type": "string"}},
        },
    },
    "permissions": {
        "read": [
            "**/requirements.txt",
            "**/package.json",
            "**/Cargo.toml",
            "**/go.mod",
            "**/pyproject.toml",
            "**/setup.py",
        ],
        "write": [],
        "execute": True,  # To run pip list, npm outdated, etc.
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Agent Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _extract_json_payload(text: str) -> str:
    """Extract JSON object from plain text or fenced markdown."""
    body = (text or "").strip()
    if not body:
        return "{}"

    fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", body, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    start = body.find("{")
    end = body.rfind("}")
    if start != -1 and end != -1 and end > start:
        return body[start : end + 1].strip()

    return "{}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


async def _run_specialized_task(
    *,
    prompt: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Run a crew task with optional user/model overrides."""
    user_id = str(kwargs.get("user_id", "default"))
    model = str(kwargs.get("model", "local"))
    return await run_crew(
        user_message=prompt,
        user_id=user_id,
        model=model,
    )


def _parse_json_response(response_text: str) -> dict[str, Any]:
    payload = _extract_json_payload(response_text)
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Agent Handlers
# ─────────────────────────────────────────────────────────────────────────────

async def handle_code_review(task: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    Handle code review task.
    
    Args:
        task: Task parameters (path, focus, max_issues)
        **kwargs: Additional arguments
    
    Returns:
        Review results
    """
    target_path = str(task.get("path", "."))
    focus = str(task.get("focus", "all"))
    max_issues = max(1, min(_safe_int(task.get("max_issues", 20), 20), 100))

    prompt = f"""
You are a strict code review agent. Review the repository path below using tool calls.
Path: {target_path}
Focus: {focus}
Maximum findings: {max_issues}

Return ONLY valid JSON with this exact shape:
{{
  "findings": [
    {{
      "file": "path/to/file.py",
      "line": 123,
      "severity": "critical|high|medium|low|info",
      "category": "security|performance|style|correctness|maintainability",
      "message": "what is wrong",
      "suggestion": "specific fix"
    }}
  ],
  "summary": "short factual summary",
  "score": {{
    "security": 0,
    "performance": 0,
    "style": 0,
    "overall": 0
  }}
}}

Rules:
- Use evidence from files/tools only.
- Do not invent CVEs or line numbers.
- Keep findings sorted by severity.
- If no issues are found, return an empty findings array and explain why.
"""

    result = await _run_specialized_task(prompt=prompt, kwargs=kwargs)
    parsed = _parse_json_response(str(result.get("response", "")))

    findings = parsed.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    score = parsed.get("score", {}) if isinstance(parsed.get("score"), dict) else {}
    normalized_score = {
        "security": max(0, min(_safe_int(score.get("security", 0), 0), 100)),
        "performance": max(0, min(_safe_int(score.get("performance", 0), 0), 100)),
        "style": max(0, min(_safe_int(score.get("style", 0), 0), 100)),
        "overall": max(0, min(_safe_int(score.get("overall", 0), 0), 100)),
    }

    return {
        "findings": findings[:max_issues],
        "summary": str(
            parsed.get("summary")
            or result.get("response")
            or "No structured review output was produced."
        ),
        "score": normalized_score,
    }


async def handle_workspace_analysis(task: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    Handle workspace analysis task.
    
    Args:
        task: Task parameters (project_path, depth, include_hidden)
        **kwargs: Additional arguments
    
    Returns:
        Analysis results
    """
    project_path = str(task.get("project_path", "."))
    depth = max(1, min(_safe_int(task.get("depth", 3), 3), 10))
    include_hidden = bool(task.get("include_hidden", False))

    prompt = f"""
You are a workspace analysis agent. Analyze this project path with tools:
Path: {project_path}
Depth: {depth}
Include hidden directories: {include_hidden}

Return ONLY valid JSON with this exact shape:
{{
  "structure": {{
    "root": "{project_path}",
    "top_level": ["src", "tests"]
  }},
  "dependencies": [
    {{
      "name": "dependency-name",
      "version": "1.2.3",
      "type": "python|node|rust|go|other"
    }}
  ],
  "tech_stack": ["Python", "FastAPI", "React"],
  "recommendations": ["specific recommendation"],
  "metrics": {{
    "total_files": 0,
    "total_dirs": 0,
    "code_files": 0,
    "config_files": 0,
    "docs_files": 0
  }}
}}

Rules:
- Base results only on inspected files.
- Keep recommendations concrete and actionable.
- If a value is unknown, use an empty list or 0 instead of guessing.
"""

    result = await _run_specialized_task(prompt=prompt, kwargs=kwargs)
    parsed = _parse_json_response(str(result.get("response", "")))

    metrics = parsed.get("metrics", {}) if isinstance(parsed.get("metrics"), dict) else {}

    return {
        "structure": parsed.get("structure", {}) if isinstance(parsed.get("structure"), dict) else {},
        "dependencies": parsed.get("dependencies", []) if isinstance(parsed.get("dependencies"), list) else [],
        "tech_stack": parsed.get("tech_stack", []) if isinstance(parsed.get("tech_stack"), list) else [],
        "recommendations": parsed.get("recommendations", []) if isinstance(parsed.get("recommendations"), list) else [],
        "metrics": {
            "total_files": max(0, _safe_int(metrics.get("total_files", 0), 0)),
            "total_dirs": max(0, _safe_int(metrics.get("total_dirs", 0), 0)),
            "code_files": max(0, _safe_int(metrics.get("code_files", 0), 0)),
            "config_files": max(0, _safe_int(metrics.get("config_files", 0), 0)),
            "docs_files": max(0, _safe_int(metrics.get("docs_files", 0), 0)),
        },
    }


async def handle_test_generation(task: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    Handle test generation task.
    
    Args:
        task: Task parameters (source_path, test_framework, coverage_target)
        **kwargs: Additional arguments
    
    Returns:
        Generation results
    """
    source_path = str(task.get("source_path", "."))
    test_framework = str(task.get("test_framework", "pytest"))
    coverage_target = max(10, min(_safe_int(task.get("coverage_target", 80), 80), 100))
    include_integration = bool(task.get("include_integration", False))

    prompt = f"""
You are a test generation planning agent. Inspect source code with tools.
Source path: {source_path}
Framework: {test_framework}
Coverage target: {coverage_target}
Include integration tests: {include_integration}

Return ONLY valid JSON with this exact shape:
{{
  "tests_generated": [
    {{
      "file": "tests/test_example.py",
      "function": "target_function",
      "test_name": "test_target_function_happy_path",
      "coverage": "branch/edge/error paths covered"
    }}
  ],
  "coverage_estimate": 0.0,
  "files_created": ["tests/test_example.py"],
  "recommendations": ["specific next step"]
}}

Rules:
- Use evidence from inspected code only.
- Do not claim files were created unless tool output proves it.
- coverage_estimate must be numeric 0..100.
"""

    result = await _run_specialized_task(prompt=prompt, kwargs=kwargs)
    parsed = _parse_json_response(str(result.get("response", "")))

    return {
        "tests_generated": parsed.get("tests_generated", []) if isinstance(parsed.get("tests_generated"), list) else [],
        "coverage_estimate": max(0.0, min(_safe_float(parsed.get("coverage_estimate", 0.0), 0.0), 100.0)),
        "files_created": parsed.get("files_created", []) if isinstance(parsed.get("files_created"), list) else [],
        "recommendations": parsed.get("recommendations", []) if isinstance(parsed.get("recommendations"), list) else [],
    }


async def handle_dependency_audit(task: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """
    Handle dependency audit task.
    
    Args:
        task: Task parameters (project_path, check_outdated, check_vulnerabilities)
        **kwargs: Additional arguments
    
    Returns:
        Audit results
    """
    project_path = str(task.get("project_path", "."))
    check_outdated = bool(task.get("check_outdated", True))
    check_vulnerabilities = bool(task.get("check_vulnerabilities", True))
    check_unused = bool(task.get("check_unused", False))

    prompt = f"""
You are a dependency audit agent. Analyze dependency manifests and available audit outputs.
Project path: {project_path}
Check outdated: {check_outdated}
Check vulnerabilities: {check_vulnerabilities}
Check unused: {check_unused}

Return ONLY valid JSON with this exact shape:
{{
  "outdated": [
    {{
      "name": "package-name",
      "current": "1.0.0",
      "latest": "1.2.0",
      "severity": "low|medium|high|critical|unknown"
    }}
  ],
  "vulnerabilities": [
    {{
      "name": "package-name",
      "version": "1.0.0",
      "cve": "CVE-XXXX-YYYY or N/A",
      "severity": "low|medium|high|critical|unknown",
      "fixed_in": "version or unknown"
    }}
  ],
  "unused": ["dependency-name"],
  "recommendations": ["specific recommendation"]
}}

Rules:
- Do not invent vulnerabilities or versions.
- If no trustworthy evidence exists, leave lists empty and explain in recommendations.
- Prefer machine-readable audit output from tools when available.
"""

    result = await _run_specialized_task(prompt=prompt, kwargs=kwargs)
    parsed = _parse_json_response(str(result.get("response", "")))

    return {
        "outdated": parsed.get("outdated", []) if isinstance(parsed.get("outdated"), list) else [],
        "vulnerabilities": parsed.get("vulnerabilities", []) if isinstance(parsed.get("vulnerabilities"), list) else [],
        "unused": parsed.get("unused", []) if isinstance(parsed.get("unused"), list) else [],
        "recommendations": parsed.get("recommendations", []) if isinstance(parsed.get("recommendations"), list) else [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

def register_tier1_agents() -> None:
    """
    Register all Tier 1 agents with the A2A registry.
    """
    # Code Reviewer
    register_agent(
        agent_id=CODE_REVIEWER_CARD["agent_id"],
        name=CODE_REVIEWER_CARD["name"],
        description=CODE_REVIEWER_CARD["description"],
        capabilities=CODE_REVIEWER_CARD["capabilities"],
        input_schema=CODE_REVIEWER_CARD["input_schema"],
        output_schema=CODE_REVIEWER_CARD["output_schema"],
        permissions=CODE_REVIEWER_CARD["permissions"],
        handler=handle_code_review,
    )
    logger.info(f"Registered Tier 1 agent: {CODE_REVIEWER_CARD['agent_id']}")
    
    # Workspace Analyzer
    register_agent(
        agent_id=WORKSPACE_ANALYZER_CARD["agent_id"],
        name=WORKSPACE_ANALYZER_CARD["name"],
        description=WORKSPACE_ANALYZER_CARD["description"],
        capabilities=WORKSPACE_ANALYZER_CARD["capabilities"],
        input_schema=WORKSPACE_ANALYZER_CARD["input_schema"],
        output_schema=WORKSPACE_ANALYZER_CARD["output_schema"],
        permissions=WORKSPACE_ANALYZER_CARD["permissions"],
        handler=handle_workspace_analysis,
    )
    logger.info(f"Registered Tier 1 agent: {WORKSPACE_ANALYZER_CARD['agent_id']}")
    
    # Test Generator
    register_agent(
        agent_id=TEST_GENERATOR_CARD["agent_id"],
        name=TEST_GENERATOR_CARD["name"],
        description=TEST_GENERATOR_CARD["description"],
        capabilities=TEST_GENERATOR_CARD["capabilities"],
        input_schema=TEST_GENERATOR_CARD["input_schema"],
        output_schema=TEST_GENERATOR_CARD["output_schema"],
        permissions=TEST_GENERATOR_CARD["permissions"],
        handler=handle_test_generation,
    )
    logger.info(f"Registered Tier 1 agent: {TEST_GENERATOR_CARD['agent_id']}")
    
    # Dependency Auditor
    register_agent(
        agent_id=DEPENDENCY_AUDITOR_CARD["agent_id"],
        name=DEPENDENCY_AUDITOR_CARD["name"],
        description=DEPENDENCY_AUDITOR_CARD["description"],
        capabilities=DEPENDENCY_AUDITOR_CARD["capabilities"],
        input_schema=DEPENDENCY_AUDITOR_CARD["input_schema"],
        output_schema=DEPENDENCY_AUDITOR_CARD["output_schema"],
        permissions=DEPENDENCY_AUDITOR_CARD["permissions"],
        handler=handle_dependency_audit,
    )
    logger.info(f"Registered Tier 1 agent: {DEPENDENCY_AUDITOR_CARD['agent_id']}")
    
    logger.info("All Tier 1 agents registered successfully")


def get_tier1_agent_ids() -> list[str]:
    """Get list of Tier 1 agent IDs."""
    return [
        CODE_REVIEWER_CARD["agent_id"],
        WORKSPACE_ANALYZER_CARD["agent_id"],
        TEST_GENERATOR_CARD["agent_id"],
        DEPENDENCY_AUDITOR_CARD["agent_id"],
    ]
