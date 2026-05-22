"""Tests for the memory parser module."""

import tempfile
from pathlib import Path

from hermes_memorex.memory_parser import (
    MemoryEntry,
    ParsedMemory,
    parse_markdown_memory,
    parse_all_memory,
    search_memory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MEMORY_MD = """\
# Agent Memory

## Episodic Memory

- [2026-01-15] User asked about deploying Python app to AWS Lambda
- [2026-02-10] Worked on React dashboard with TypeScript
- [2026-03-05] Debugged PostgreSQL connection pooling issue
- [2026-04-20] User requested help with Docker containerization

## Semantic Memory

- Python is the user's primary programming language
- The project uses Next.js with TypeScript for the frontend
- User prefers dark mode in all applications
- AWS Lambda is used for serverless deployments

## Key Facts

- Name: Alex Chen
- Role: Senior Full-Stack Engineer
- Team: Platform Engineering
- Preferred editor: VS Code
"""

SAMPLE_USER_MD = """\
# User Profile

## About the User

- Name: Alex Chen
- Communication style: Direct, technical, prefers code examples
- Timezone: UTC-8 (Pacific)

## Preferences

- Dark mode everywhere
- Python over JavaScript for backend
- Docker for all deployments
- Prefers functional programming patterns
"""


def _write_temp_file(content: str, filename: str, tmpdir: Path) -> Path:
    """Write content to a temp file and return its path."""
    filepath = tmpdir / filename
    filepath.write_text(content, encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# parse_markdown_memory tests
# ---------------------------------------------------------------------------

class TestParseMarkdownMemory:
    """Tests for parsing individual markdown memory files."""

    def test_parses_bullet_points(self, tmp_path: Path):
        filepath = _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        entries = parse_markdown_memory(filepath)

        assert len(entries) > 0
        # Should have episodic, semantic, and fact entries
        types = {e.entry_type for e in entries}
        assert "episodic" in types
        assert "semantic" in types

    def test_extracts_timestamps(self, tmp_path: Path):
        filepath = _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        entries = parse_markdown_memory(filepath)

        timestamped = [e for e in entries if e.timestamp is not None]
        assert len(timestamped) >= 4  # The 4 episodic entries
        assert timestamped[0].timestamp == "2026-01-15"

    def test_classifies_sections(self, tmp_path: Path):
        filepath = _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        entries = parse_markdown_memory(filepath)

        episodic = [e for e in entries if e.entry_type == "episodic"]
        semantic = [e for e in entries if e.entry_type == "semantic"]
        assert len(episodic) >= 4
        assert len(semantic) >= 4

    def test_preserves_source(self, tmp_path: Path):
        filepath = _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        entries = parse_markdown_memory(filepath)

        assert all(e.source == "MEMORY.md" for e in entries)

    def test_handles_user_md(self, tmp_path: Path):
        filepath = _write_temp_file(SAMPLE_USER_MD, "USER.md", tmp_path)
        entries = parse_markdown_memory(filepath)

        assert len(entries) > 0
        user_entries = [e for e in entries if e.entry_type == "user"]
        assert len(user_entries) > 0

    def test_handles_nonexistent_file(self):
        entries = parse_markdown_memory("/nonexistent/MEMORY.md")
        assert entries == []

    def test_handles_empty_file(self, tmp_path: Path):
        filepath = _write_temp_file("", "MEMORY.md", tmp_path)
        entries = parse_markdown_memory(filepath)
        assert entries == []

    def test_key_value_extraction(self, tmp_path: Path):
        filepath = _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        entries = parse_markdown_memory(filepath)

        # Should extract key-value pairs from "Key Facts" section
        fact_contents = [e.content for e in entries]
        assert any("Alex Chen" in c for c in fact_contents)


# ---------------------------------------------------------------------------
# parse_all_memory tests
# ---------------------------------------------------------------------------

class TestParseAllMemory:
    """Tests for the unified memory parser."""

    def test_parses_hermes_dir(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        _write_temp_file(SAMPLE_USER_MD, "USER.md", tmp_path)

        result = parse_all_memory(tmp_path)
        assert isinstance(result, ParsedMemory)
        assert len(result.entries) > 0
        assert len(result.sources) == 2

    def test_handles_missing_dir(self):
        result = parse_all_memory("/nonexistent/dir")
        assert len(result.entries) == 0
        assert len(result.parse_errors) > 0

    def test_sorts_by_timestamp(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        result = parse_all_memory(tmp_path)

        timestamped = [e for e in result.entries if e.timestamp]
        for i in range(len(timestamped) - 1):
            assert timestamped[i].timestamp <= timestamped[i + 1].timestamp


# ---------------------------------------------------------------------------
# search_memory tests
# ---------------------------------------------------------------------------

class TestSearchMemory:
    """Tests for memory search functionality."""

    def test_finds_matching_entries(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        parsed = parse_all_memory(tmp_path)

        results = search_memory(parsed, "Python")
        assert results["total"] > 0
        assert all("python" in r["content"].lower() for r in results["results"])

    def test_respects_type_filter(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        parsed = parse_all_memory(tmp_path)

        results = search_memory(parsed, "Python", memory_type="episodic")
        for r in results["results"]:
            assert r["entry_type"] == "episodic"

    def test_respects_limit(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        parsed = parse_all_memory(tmp_path)

        results = search_memory(parsed, "the", limit=2)
        assert len(results["results"]) <= 2

    def test_returns_relevance_scores(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        parsed = parse_all_memory(tmp_path)

        results = search_memory(parsed, "Python")
        for r in results["results"]:
            assert 0 <= r["relevance"] <= 1

    def test_sorted_by_relevance(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        parsed = parse_all_memory(tmp_path)

        results = search_memory(parsed, "Python")
        scores = [r["relevance"] for r in results["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_empty_query_returns_empty(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        parsed = parse_all_memory(tmp_path)

        results = search_memory(parsed, "")
        assert results["total"] == 0

    def test_no_match_returns_empty(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        parsed = parse_all_memory(tmp_path)

        results = search_memory(parsed, "xyzzynonexistent")
        assert results["total"] == 0

    def test_includes_highlights(self, tmp_path: Path):
        _write_temp_file(SAMPLE_MEMORY_MD, "MEMORY.md", tmp_path)
        parsed = parse_all_memory(tmp_path)

        results = search_memory(parsed, "Python")
        for r in results["results"]:
            assert isinstance(r["highlights"], list)
