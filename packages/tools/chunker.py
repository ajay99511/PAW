"""
Smart Chunker — split parsed documents into semantically coherent chunks.

Strategies:
  - Recursive:      Split on paragraphs, then sentences, with configurable
                    size and overlap. Best for prose/docs.
  - Code-aware:     Respect function/class boundaries. Never split mid-function.
  - Markdown-aware: Split on headers, preserving header hierarchy as metadata.

Usage:
    from packages.tools.chunker import chunk_document
    chunks = chunk_document(parsed_doc, strategy="auto")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from packages.tools.parsers import ParsedDocument

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE = 512       # target tokens (≈ chars / 4)
DEFAULT_CHUNK_CHARS = 2048     # ≈ 512 tokens
DEFAULT_OVERLAP_RATIO = 0.15   # 15% overlap between chunks
MIN_CHUNK_CHARS = 100          # never create chunks smaller than this


# ── Data Models ──────────────────────────────────────────────────────


@dataclass
class Chunk:
    """A single chunk of text from a document."""
    text: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Public API ───────────────────────────────────────────────────────


def chunk_document(
    doc: ParsedDocument,
    strategy: Literal["auto", "recursive", "code", "markdown"] = "auto",
    chunk_size: int = DEFAULT_CHUNK_CHARS,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[Chunk]:
    """
    Split a ParsedDocument into chunks using the specified strategy.

    Args:
        doc:           The parsed document to chunk.
        strategy:      "auto" selects based on file type.
        chunk_size:    Target chunk size in characters.
        overlap_ratio: Fraction of chunk_size to overlap.

    Returns:
        List of Chunk objects with metadata.
    """
    if strategy == "auto":
        strategy = _auto_strategy(doc)

    chunker = _STRATEGIES.get(strategy, _chunk_recursive)

    raw_chunks = chunker(doc, chunk_size, overlap_ratio)

    # Enrich all chunks with source metadata
    enriched = []
    for i, chunk in enumerate(raw_chunks):
        chunk.chunk_index = i
        chunk.metadata = {
            **chunk.metadata,
            "source_path": doc.source_path,
            "file_type": doc.file_type,
            "chunk_index": i,
            "total_chunks": len(raw_chunks),
        }
        enriched.append(chunk)

    logger.info(
        "Chunked %s into %d chunks (strategy=%s, chunk_size=%d)",
        doc.source_path, len(enriched), strategy, chunk_size,
    )
    return enriched


# ── Strategy: Auto-detect ────────────────────────────────────────────


def _auto_strategy(doc: ParsedDocument) -> str:
    """Pick the best chunking strategy based on file type."""
    if doc.file_type in ("python", "javascript"):
        return "code"
    elif doc.file_type == "markdown":
        return "markdown"
    else:
        return "recursive"


# ── Strategy: Recursive ──────────────────────────────────────────────


def _chunk_recursive(
    doc: ParsedDocument,
    chunk_size: int,
    overlap_ratio: float,
) -> list[Chunk]:
    """
    Recursively split text on paragraph boundaries, then sentences.

    Produces chunks of approximately `chunk_size` characters with
    `overlap_ratio` overlap between consecutive chunks.
    """
    text = doc.text.strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [Chunk(text=text, chunk_index=0)]

    overlap = int(chunk_size * overlap_ratio)
    separators = ["\n\n", "\n", ". ", " "]

    return _recursive_split(text, chunk_size, overlap, separators)


def _recursive_split(
    text: str,
    chunk_size: int,
    overlap: int,
    separators: list[str],
) -> list[Chunk]:
    """Recursively split text using a hierarchy of separators."""
    if len(text) <= chunk_size:
        return [Chunk(text=text, chunk_index=0)]

    # Try each separator in order
    for sep in separators:
        parts = text.split(sep)
        if len(parts) > 1:
            chunks = []
            current = ""

            for part in parts:
                candidate = current + sep + part if current else part
                if len(candidate) > chunk_size and current:
                    chunks.append(Chunk(text=current.strip(), chunk_index=0))
                    # Apply overlap: keep the tail of the current chunk
                    if overlap > 0 and len(current) > overlap:
                        current = current[-overlap:] + sep + part
                    else:
                        current = part
                else:
                    current = candidate

            if current.strip():
                chunks.append(Chunk(text=current.strip(), chunk_index=0))

            # Filter out tiny chunks
            chunks = [c for c in chunks if len(c.text) >= MIN_CHUNK_CHARS]
            if chunks:
                return chunks

    # Last resort: hard split by character count
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunk_text = text[i:i + chunk_size].strip()
        if chunk_text and len(chunk_text) >= MIN_CHUNK_CHARS:
            chunks.append(Chunk(text=chunk_text, chunk_index=0))

    return chunks


# ── Strategy: Code-aware ─────────────────────────────────────────────


def _chunk_code(
    doc: ParsedDocument,
    chunk_size: int,
    overlap_ratio: float,
) -> list[Chunk]:
    """
    Chunk code files respecting function/class boundaries.

    Each top-level function or class becomes its own chunk.
    Large functions are split recursively within their body.
    Imports and module-level code form the first chunk.
    """
    text = doc.text
    lines = text.split("\n")
    sections = doc.sections

    if not sections:
        # No structure detected, fall back to recursive
        return _chunk_recursive(doc, chunk_size, overlap_ratio)

    chunks = []

    # 1. Module header (imports, module docstring, etc.)
    first_section_line = sections[0].get("line_number", 1)
    if first_section_line > 1:
        header_text = "\n".join(lines[:first_section_line - 1]).strip()
        if header_text and len(header_text) >= MIN_CHUNK_CHARS:
            chunks.append(Chunk(
                text=header_text,
                chunk_index=0,
                metadata={"section": "module_header"},
            ))

    # 2. Each function/class as its own chunk
    for idx, section in enumerate(sections):
        start_line = section.get("line_number", 1) - 1
        indent = section.get("indent", 0)

        # Find the end of this section (next section at same or lower indent)
        end_line = len(lines)
        for next_section in sections[idx + 1:]:
            if next_section.get("indent", 0) <= indent:
                end_line = next_section.get("line_number", len(lines) + 1) - 1
                break

        section_text = "\n".join(lines[start_line:end_line]).strip()

        if not section_text:
            continue

        # If section is larger than chunk_size, split it further
        if len(section_text) > chunk_size:
            sub_doc = ParsedDocument(
                text=section_text,
                source_path=doc.source_path,
                file_type=doc.file_type,
            )
            sub_chunks = _chunk_recursive(sub_doc, chunk_size, overlap_ratio)
            for sc in sub_chunks:
                sc.metadata["section"] = section.get("name", "unknown")
                sc.metadata["section_kind"] = section.get("kind", "unknown")
                chunks.append(sc)
        else:
            chunks.append(Chunk(
                text=section_text,
                chunk_index=0,
                metadata={
                    "section": section.get("name", "unknown"),
                    "section_kind": section.get("kind", "unknown"),
                    "line_number": section.get("line_number", 0),
                },
            ))

    return chunks


# ── Strategy: Markdown-aware ─────────────────────────────────────────


def _chunk_markdown(
    doc: ParsedDocument,
    chunk_size: int,
    overlap_ratio: float,
) -> list[Chunk]:
    """
    Chunk Markdown files by header boundaries.

    Each header section becomes a chunk. Large sections are
    split recursively. Header hierarchy is preserved as metadata.
    """
    text = doc.text
    sections = doc.sections

    if not sections:
        return _chunk_recursive(doc, chunk_size, overlap_ratio)

    chunks = []

    # Split text at each header position
    for idx, section in enumerate(sections):
        start = section["start_pos"]
        end = sections[idx + 1]["start_pos"] if idx + 1 < len(sections) else len(text)

        section_text = text[start:end].strip()
        if not section_text:
            continue

        header_meta = {
            "section_title": section["title"],
            "section_level": section["level"],
        }

        if len(section_text) > chunk_size:
            sub_doc = ParsedDocument(
                text=section_text,
                source_path=doc.source_path,
                file_type="text",
            )
            sub_chunks = _chunk_recursive(sub_doc, chunk_size, overlap_ratio)
            for sc in sub_chunks:
                sc.metadata.update(header_meta)
                chunks.append(sc)
        else:
            chunks.append(Chunk(
                text=section_text,
                chunk_index=0,
                metadata=header_meta,
            ))

    # Handle content before the first header
    if sections and sections[0]["start_pos"] > 0:
        preamble = text[:sections[0]["start_pos"]].strip()
        if preamble and len(preamble) >= MIN_CHUNK_CHARS:
            chunks.insert(0, Chunk(
                text=preamble,
                chunk_index=0,
                metadata={"section_title": "preamble", "section_level": 0},
            ))

    return chunks


# ── Strategy Registry ────────────────────────────────────────────────

_STRATEGIES = {
    "recursive": _chunk_recursive,
    "code": _chunk_code,
    "markdown": _chunk_markdown,
}
