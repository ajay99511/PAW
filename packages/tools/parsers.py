"""
File Parsers — extract text + metadata from various file types.

Supported formats:
  - Markdown (.md)
  - Plain text (.txt, .log, .csv)
  - Python (.py)
  - JavaScript/TypeScript (.js, .ts, .jsx, .tsx)
  - JSON (.json)
  - YAML (.yaml, .yml)
  - PDF (.pdf) — via pymupdf

Each parser returns a ParsedDocument with the full text,
source metadata, and structural hints for the chunker.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Data Models ──────────────────────────────────────────────────────


@dataclass
class ParsedDocument:
    """Result of parsing a single file."""
    text: str
    source_path: str
    file_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)


# ── File Extension → Parser Mapping ─────────────────────────────────

_EXTENSION_MAP: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".log": "text",
    ".csv": "text",
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
    ".jsx": "javascript",
    ".tsx": "javascript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".pdf": "pdf",
    ".env": "text",
    ".cfg": "text",
    ".ini": "text",
    ".toml": "text",
    ".rst": "text",
}


def detect_file_type(path: Path) -> str:
    """Detect the parser type for a file based on its extension."""
    return _EXTENSION_MAP.get(path.suffix.lower(), "text")


# ── Parsers ──────────────────────────────────────────────────────────


def parse_file(path: Path) -> ParsedDocument:
    """
    Parse a file and return a ParsedDocument.

    Automatically selects the right parser based on file extension.
    """
    file_type = detect_file_type(path)
    parser = _PARSERS.get(file_type, _parse_text)

    try:
        return parser(path)
    except Exception as exc:
        logger.error("Failed to parse %s: %s", path, exc)
        raise


def _parse_text(path: Path) -> ParsedDocument:
    """Parse plain text files."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return ParsedDocument(
        text=text,
        source_path=str(path),
        file_type="text",
        metadata={
            "filename": path.name,
            "extension": path.suffix,
            "size_bytes": path.stat().st_size,
        },
    )


def _parse_markdown(path: Path) -> ParsedDocument:
    """
    Parse Markdown files with header extraction.

    Extracts section structure (h1-h6) for header-aware chunking.
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    # Extract headers with their line positions
    sections = []
    header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    for match in header_pattern.finditer(text):
        sections.append({
            "level": len(match.group(1)),
            "title": match.group(2).strip(),
            "start_pos": match.start(),
        })

    return ParsedDocument(
        text=text,
        source_path=str(path),
        file_type="markdown",
        metadata={
            "filename": path.name,
            "extension": path.suffix,
            "size_bytes": path.stat().st_size,
            "header_count": len(sections),
        },
        sections=sections,
    )


def _parse_python(path: Path) -> ParsedDocument:
    """
    Parse Python files with function/class boundary detection.

    Extracts top-level functions and classes as sections
    so the chunker can respect code boundaries.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    sections = []
    # Match top-level and nested definitions
    def_pattern = re.compile(r"^(\s*)(class|def|async\s+def)\s+(\w+)")

    for i, line in enumerate(lines):
        match = def_pattern.match(line)
        if match:
            indent = len(match.group(1))
            kind = "class" if "class" in match.group(2) else "function"
            name = match.group(3)
            sections.append({
                "kind": kind,
                "name": name,
                "indent": indent,
                "line_number": i + 1,
                "start_pos": sum(len(l) + 1 for l in lines[:i]),
            })

    return ParsedDocument(
        text=text,
        source_path=str(path),
        file_type="python",
        metadata={
            "filename": path.name,
            "extension": path.suffix,
            "size_bytes": path.stat().st_size,
            "functions": [s["name"] for s in sections if s["kind"] == "function"],
            "classes": [s["name"] for s in sections if s["kind"] == "class"],
        },
        sections=sections,
    )


def _parse_javascript(path: Path) -> ParsedDocument:
    """Parse JavaScript/TypeScript files with function detection."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")

    sections = []
    # Match various JS/TS patterns
    patterns = [
        re.compile(r"^(\s*)(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^(\s*)(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\("),
        re.compile(r"^(\s*)(?:export\s+)?class\s+(\w+)"),
    ]

    for i, line in enumerate(lines):
        for pattern in patterns:
            match = pattern.match(line)
            if match:
                sections.append({
                    "kind": "class" if "class" in pattern.pattern else "function",
                    "name": match.group(2),
                    "indent": len(match.group(1)),
                    "line_number": i + 1,
                    "start_pos": sum(len(l) + 1 for l in lines[:i]),
                })
                break

    return ParsedDocument(
        text=text,
        source_path=str(path),
        file_type="javascript",
        metadata={
            "filename": path.name,
            "extension": path.suffix,
            "size_bytes": path.stat().st_size,
        },
        sections=sections,
    )


def _parse_json(path: Path) -> ParsedDocument:
    """Parse JSON files with pretty-printing for readability."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        text = raw  # Fall back to raw text if invalid JSON

    return ParsedDocument(
        text=text,
        source_path=str(path),
        file_type="json",
        metadata={
            "filename": path.name,
            "extension": path.suffix,
            "size_bytes": path.stat().st_size,
        },
    )


def _parse_yaml(path: Path) -> ParsedDocument:
    """Parse YAML files as plain text (preserving structure)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return ParsedDocument(
        text=text,
        source_path=str(path),
        file_type="yaml",
        metadata={
            "filename": path.name,
            "extension": path.suffix,
            "size_bytes": path.stat().st_size,
        },
    )


def _parse_pdf(path: Path) -> ParsedDocument:
    """
    Parse PDF files using pymupdf4llm for text extraction.

    Falls back to basic pymupdf if pymupdf4llm is not available.
    """
    try:
        import pymupdf  # noqa: F811
    except ImportError:
        raise ImportError(
            "pymupdf is required for PDF parsing. "
            "Install it with: pip install pymupdf"
        )

    doc = pymupdf.open(str(path))
    pages = []
    sections = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page.get_text("text")
        if page_text.strip():
            pages.append(page_text)
            sections.append({
                "kind": "page",
                "name": f"Page {page_num + 1}",
                "start_pos": sum(len(p) for p in pages[:-1]),
                "line_number": page_num + 1,
            })

    doc.close()

    text = "\n\n".join(pages)

    return ParsedDocument(
        text=text,
        source_path=str(path),
        file_type="pdf",
        metadata={
            "filename": path.name,
            "extension": path.suffix,
            "size_bytes": path.stat().st_size,
            "page_count": len(pages),
        },
        sections=sections,
    )


# ── Parser Registry ──────────────────────────────────────────────────

_PARSERS: dict[str, Any] = {
    "text": _parse_text,
    "markdown": _parse_markdown,
    "python": _parse_python,
    "javascript": _parse_javascript,
    "json": _parse_json,
    "yaml": _parse_yaml,
    "pdf": _parse_pdf,
}
