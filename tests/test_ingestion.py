"""
Unit tests for the document ingestion pipeline.

Tests parsers and chunker independently (no external dependencies needed).
"""

import tempfile
from pathlib import Path

import pytest

from packages.tools.parsers import parse_file, detect_file_type, ParsedDocument
from packages.tools.chunker import chunk_document, Chunk


# ── Parser Tests ─────────────────────────────────────────────────────


class TestDetectFileType:
    def test_markdown(self):
        assert detect_file_type(Path("readme.md")) == "markdown"

    def test_python(self):
        assert detect_file_type(Path("main.py")) == "python"

    def test_javascript(self):
        assert detect_file_type(Path("index.js")) == "javascript"
        assert detect_file_type(Path("app.tsx")) == "javascript"

    def test_json(self):
        assert detect_file_type(Path("config.json")) == "json"

    def test_yaml(self):
        assert detect_file_type(Path("docker-compose.yml")) == "yaml"
        assert detect_file_type(Path("config.yaml")) == "yaml"

    def test_unknown_defaults_to_text(self):
        assert detect_file_type(Path("file.xyz")) == "text"

    def test_pdf(self):
        assert detect_file_type(Path("document.pdf")) == "pdf"


class TestParseMarkdown:
    def test_basic_markdown(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text("# Title\n\nSome content.\n\n## Section 1\n\nMore content.", encoding="utf-8")

        doc = parse_file(md_file)

        assert isinstance(doc, ParsedDocument)
        assert doc.file_type == "markdown"
        assert doc.metadata["header_count"] == 2
        assert len(doc.sections) == 2
        assert doc.sections[0]["title"] == "Title"
        assert doc.sections[0]["level"] == 1
        assert doc.sections[1]["title"] == "Section 1"
        assert doc.sections[1]["level"] == 2

    def test_empty_markdown(self, tmp_path):
        md_file = tmp_path / "empty.md"
        md_file.write_text("", encoding="utf-8")

        doc = parse_file(md_file)
        assert doc.text == ""
        assert doc.metadata["header_count"] == 0


class TestParsePython:
    def test_python_with_functions(self, tmp_path):
        py_file = tmp_path / "example.py"
        py_file.write_text(
            'import os\n\ndef hello():\n    print("hi")\n\nclass MyClass:\n    def method(self):\n        pass\n',
            encoding="utf-8",
        )

        doc = parse_file(py_file)

        assert doc.file_type == "python"
        assert "hello" in doc.metadata["functions"]
        assert "MyClass" in doc.metadata["classes"]
        assert len(doc.sections) >= 2  # hello() + MyClass

    def test_python_with_async(self, tmp_path):
        py_file = tmp_path / "async_example.py"
        py_file.write_text(
            "async def fetch_data():\n    return 42\n",
            encoding="utf-8",
        )

        doc = parse_file(py_file)
        assert "fetch_data" in doc.metadata["functions"]


class TestParseJson:
    def test_valid_json(self, tmp_path):
        json_file = tmp_path / "config.json"
        json_file.write_text('{"key": "value", "nested": {"a": 1}}', encoding="utf-8")

        doc = parse_file(json_file)
        assert doc.file_type == "json"
        assert '"key": "value"' in doc.text

    def test_invalid_json_fallback(self, tmp_path):
        json_file = tmp_path / "bad.json"
        json_file.write_text("{not valid json}", encoding="utf-8")

        doc = parse_file(json_file)
        assert doc.text == "{not valid json}"


class TestParsePlainText:
    def test_text_file(self, tmp_path):
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Some plain text notes.", encoding="utf-8")

        doc = parse_file(txt_file)
        assert doc.file_type == "text"
        assert doc.text == "Some plain text notes."


# ── Chunker Tests ────────────────────────────────────────────────────


class TestChunkRecursive:
    def test_small_text_single_chunk(self):
        doc = ParsedDocument(
            text="Short text.",
            source_path="test.txt",
            file_type="text",
        )
        chunks = chunk_document(doc, strategy="recursive")
        assert len(chunks) == 1
        assert chunks[0].text == "Short text."

    def test_large_text_multiple_chunks(self):
        # Create text larger than default chunk size
        paragraphs = ["This is paragraph number %d with some filler content to make it longer." % i
                       for i in range(100)]
        text = "\n\n".join(paragraphs)

        doc = ParsedDocument(
            text=text,
            source_path="test.txt",
            file_type="text",
        )
        chunks = chunk_document(doc, strategy="recursive", chunk_size=500)
        assert len(chunks) > 1

        # All chunks should have metadata
        for chunk in chunks:
            assert "source_path" in chunk.metadata
            assert "chunk_index" in chunk.metadata

    def test_chunks_have_sequential_indices(self):
        text = "\n\n".join([f"Paragraph {i}. This is filler content for chunk testing. " * 5 for i in range(50)])
        doc = ParsedDocument(text=text, source_path="test.txt", file_type="text")
        chunks = chunk_document(doc, chunk_size=300)

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i


class TestChunkCodeAware:
    def test_python_functions_as_chunks(self):
        code = '''import os

def function_a():
    """Does something."""
    x = 1
    y = 2
    return x + y

def function_b():
    """Does another thing."""
    for i in range(10):
        print(i)
    return True

class MyClass:
    def method_one(self):
        pass

    def method_two(self):
        pass
'''
        doc = ParsedDocument(
            text=code,
            source_path="example.py",
            file_type="python",
            sections=[
                {"kind": "function", "name": "function_a", "indent": 0, "line_number": 3, "start_pos": 10},
                {"kind": "function", "name": "function_b", "indent": 0, "line_number": 9, "start_pos": 100},
                {"kind": "class", "name": "MyClass", "indent": 0, "line_number": 16, "start_pos": 200},
            ],
        )
        chunks = chunk_document(doc, strategy="code")
        assert len(chunks) >= 2  # header + functions/class

    def test_code_chunks_preserve_section_name(self):
        code = 'def my_func():\n    return 42\n'
        doc = ParsedDocument(
            text=code,
            source_path="test.py",
            file_type="python",
            sections=[
                {"kind": "function", "name": "my_func", "indent": 0, "line_number": 1, "start_pos": 0},
            ],
        )
        chunks = chunk_document(doc, strategy="code")
        # At least one chunk should mention the function section
        section_names = [c.metadata.get("section") for c in chunks]
        assert "my_func" in section_names


class TestChunkMarkdown:
    def test_markdown_header_chunks(self):
        md = "# Title\n\nIntro paragraph.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B.\n"
        doc = ParsedDocument(
            text=md,
            source_path="doc.md",
            file_type="markdown",
            sections=[
                {"level": 1, "title": "Title", "start_pos": 0},
                {"level": 2, "title": "Section A", "start_pos": md.index("## Section A")},
                {"level": 2, "title": "Section B", "start_pos": md.index("## Section B")},
            ],
        )
        chunks = chunk_document(doc, strategy="markdown")
        assert len(chunks) >= 2

        # Each chunk should have section_title metadata
        for chunk in chunks:
            assert "section_title" in chunk.metadata


class TestAutoStrategy:
    def test_python_uses_code(self):
        doc = ParsedDocument(text="def f(): pass", source_path="x.py", file_type="python")
        chunks = chunk_document(doc, strategy="auto")
        # Should work without errors (uses code strategy)
        assert len(chunks) >= 1

    def test_markdown_uses_markdown(self):
        doc = ParsedDocument(text="# Hello", source_path="x.md", file_type="markdown")
        chunks = chunk_document(doc, strategy="auto")
        assert len(chunks) >= 1

    def test_text_uses_recursive(self):
        doc = ParsedDocument(text="Just text", source_path="x.txt", file_type="text")
        chunks = chunk_document(doc, strategy="auto")
        assert len(chunks) >= 1
