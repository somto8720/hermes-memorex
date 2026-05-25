"""Memory file parser for hermes-memorex.

Parses Hermes Agent memory files (MEMORY.md, USER.md) and optional SQLite
databases to extract structured memory entries with timestamps, sections,
and content for downstream graph building and search.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """A single memory entry extracted from a memory file."""

    source: str  # e.g. "MEMORY.md", "USER.md", "memory.db"
    section: str  # e.g. "Episodic Memory", "User Profile"
    content: str
    timestamp: Optional[str] = None
    entry_type: str = "general"  # episodic, semantic, user, fact
    line_number: int = 0
    raw_line: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParsedMemory:
    """Complete parsed memory from all sources."""

    entries: list[MemoryEntry] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "sources": self.sources,
            "parse_errors": self.parse_errors,
            "total_entries": len(self.entries),
        }


# ---------------------------------------------------------------------------
# Section-to-type mapping
# ---------------------------------------------------------------------------

_SECTION_TYPE_MAP: dict[str, str] = {
    "episodic": "episodic",
    "episode": "episodic",
    "events": "episodic",
    "interactions": "episodic",
    "conversations": "episodic",
    "semantic": "semantic",
    "knowledge": "semantic",
    "facts": "semantic",
    "key facts": "semantic",
    "learned": "semantic",
    "user": "user",
    "profile": "user",
    "preferences": "user",
    "about the user": "user",
    "user profile": "user",
    "communication": "user",
}


def _classify_section(section_name: str) -> str:
    """Map a section heading to a memory type."""
    lower = section_name.lower().strip()
    for keyword, entry_type in _SECTION_TYPE_MAP.items():
        if keyword in lower:
            return entry_type
    return "general"


# ---------------------------------------------------------------------------
# Timestamp extraction
# ---------------------------------------------------------------------------

# Matches patterns like [2026-05-20], (2026-05-20T14:30:00Z), 2026-05-20 ...
_TS_PATTERNS = [
    re.compile(r"\[(\d{4}-\d{2}-\d{2}(?:T[\d:]+Z?)?)\]"),
    re.compile(r"\((\d{4}-\d{2}-\d{2}(?:T[\d:]+Z?)?)\)"),
    re.compile(r"^(\d{4}-\d{2}-\d{2}(?:T[\d:]+Z?)?)[\s:—\-]"),
]


def _extract_timestamp(line: str) -> Optional[str]:
    """Try to extract an ISO-ish timestamp from a line."""
    for pattern in _TS_PATTERNS:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def parse_markdown_memory(filepath: str | Path) -> list[MemoryEntry]:
    """Parse a markdown memory file into structured entries.

    Handles MEMORY.md and USER.md formats. Recognises:
    - H1/H2/H3 headings as section delimiters
    - Bullet points (-, *, +) as individual entries
    - Paragraphs as entries
    - Inline timestamps in [brackets] or (parens)
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return []

    entries: list[MemoryEntry] = []
    source = filepath.name
    current_section = "General"
    current_paragraph: list[str] = []
    paragraph_start_line = 0

    def _flush_paragraph():
        nonlocal current_paragraph, paragraph_start_line
        if current_paragraph:
            text = " ".join(current_paragraph).strip()
            if text:
                ts = _extract_timestamp(text)
                entries.append(
                    MemoryEntry(
                        source=source,
                        section=current_section,
                        content=text,
                        timestamp=ts,
                        entry_type=_classify_section(current_section),
                        line_number=paragraph_start_line,
                        raw_line=text,
                    )
                )
            current_paragraph = []

    try:
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()

        # Skip empty lines — flush any accumulated paragraph
        if not stripped:
            _flush_paragraph()
            continue

        # Heading detection (# Section, ## Section, ### Section)
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading_match:
            _flush_paragraph()
            current_section = heading_match.group(2).strip()
            continue

        # Bullet point — each is its own entry
        bullet_match = re.match(r"^[-*+]\s+(.+)$", stripped)
        if bullet_match:
            _flush_paragraph()
            content = bullet_match.group(1).strip()
            ts = _extract_timestamp(content)
            entries.append(
                MemoryEntry(
                    source=source,
                    section=current_section,
                    content=content,
                    timestamp=ts,
                    entry_type=_classify_section(current_section),
                    line_number=line_num,
                    raw_line=stripped,
                )
            )
            continue

        # Key-value pairs (e.g. "Name: John", "Preference: dark mode")
        kv_match = re.match(r"^[-*]?\s*\*?\*?(.+?)\*?\*?\s*:\s*(.+)$", stripped)
        if kv_match and len(stripped) < 200:
            _flush_paragraph()
            content = f"{kv_match.group(1).strip()}: {kv_match.group(2).strip()}"
            entries.append(
                MemoryEntry(
                    source=source,
                    section=current_section,
                    content=content,
                    timestamp=None,
                    entry_type=_classify_section(current_section),
                    line_number=line_num,
                    raw_line=stripped,
                )
            )
            continue

        # Otherwise accumulate as paragraph
        if not current_paragraph:
            paragraph_start_line = line_num
        current_paragraph.append(stripped)

    # Flush any remaining paragraph
    _flush_paragraph()

    return entries


# ---------------------------------------------------------------------------
# SQLite parser
# ---------------------------------------------------------------------------

def parse_sqlite_memory(db_path: str | Path) -> list[MemoryEntry]:
    """Parse a Hermes SQLite memory database.

    Tries common table/column names used by Hermes and memory providers.
    Gracefully handles missing tables or columns.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return []

    entries: list[MemoryEntry] = []

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Discover available tables
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in cursor.fetchall()}

        # Try common memory table patterns
        memory_tables = [
            ("memories", "content", "created_at", "type"),
            ("memory", "content", "timestamp", "category"),
            ("episodic_memory", "content", "created_at", "type"),
            ("facts", "fact", "created_at", "source"),
            ("entries", "text", "date", "kind"),
        ]

        for table_name, content_col, ts_col, type_col in memory_tables:
            if table_name not in tables:
                continue

            # Get actual columns for this table
            cursor.execute(f"PRAGMA table_info({table_name})")
            actual_cols = {row["name"] for row in cursor.fetchall()}

            # Build a safe SELECT with available columns
            select_cols = []
            if content_col in actual_cols:
                select_cols.append(content_col)
            else:
                # Try to find any text-ish column
                for col in actual_cols:
                    if col.lower() in ("content", "text", "fact", "data", "value"):
                        content_col = col
                        select_cols.append(col)
                        break

            if not select_cols:
                continue

            ts_available = ts_col in actual_cols
            type_available = type_col in actual_cols

            if ts_available:
                select_cols.append(ts_col)
            if type_available:
                select_cols.append(type_col)

            query = f"SELECT {', '.join(select_cols)} FROM {table_name} LIMIT 5000"
            try:
                cursor.execute(query)
                for row in cursor.fetchall():
                    content = row[content_col] if content_col in row.keys() else ""
                    if not content:
                        continue
                    entries.append(
                        MemoryEntry(
                            source=f"{db_path.name}:{table_name}",
                            section=table_name,
                            content=str(content),
                            timestamp=(
                                str(row[ts_col]) if ts_available else None
                            ),
                            entry_type=(
                                str(row[type_col]).lower()
                                if type_available
                                else "general"
                            ),
                        )
                    )
            except sqlite3.OperationalError:
                continue

        conn.close()
    except (sqlite3.Error, OSError):
        return []

    return entries


# ---------------------------------------------------------------------------
# Unified parser
# ---------------------------------------------------------------------------

def parse_all_memory(hermes_dir: Optional[str | Path] = None) -> ParsedMemory:
    """Parse all memory sources from a Hermes installation.

    Searches for MEMORY.md, USER.md, and *.db files in the Hermes
    home directory (default: ~/.hermes).

    Args:
        hermes_dir: Override path to the Hermes home directory.

    Returns:
        ParsedMemory with all extracted entries.
    """
    if hermes_dir is None:
        hermes_dir = Path.home() / ".hermes"
    else:
        hermes_dir = Path(hermes_dir)

    result = ParsedMemory()

    if not hermes_dir.exists():
        result.parse_errors.append(f"Hermes directory not found: {hermes_dir}")
        return result

    # Parse markdown memory files from hermes_dir and cwd
    memory_patterns = ["MEMORY.md", "memory.md", "USER.md", "user.md"]
    found_files = set()
    
    # 1. Check hermes_dir
    for pattern in memory_patterns:
        for filepath in hermes_dir.glob(pattern):
            if filepath.is_file():
                found_files.add(filepath.resolve())

    # 2. Check project-level memory
    cwd_hermes = Path.cwd() / ".hermes"
    if cwd_hermes.exists():
        for pattern in memory_patterns:
            for filepath in cwd_hermes.glob(pattern):
                if filepath.is_file():
                    found_files.add(filepath.resolve())

    for filepath in sorted(found_files):
        try:
            file_entries = parse_markdown_memory(filepath)
            if file_entries:
                result.entries.extend(file_entries)
                result.sources.append(str(filepath))
        except Exception as e:
            result.parse_errors.append(f"Failed to parse {filepath}: {e}")

    # Parse SQLite databases
    for db_pattern in ["*.db", "*.sqlite", "*.sqlite3"]:
        for db_path in hermes_dir.glob(db_pattern):
            entries = parse_sqlite_memory(db_path)
            if entries:
                result.entries.extend(entries)
                result.sources.append(str(db_path))

    # Sort entries by timestamp (entries without timestamps go last)
    result.entries.sort(
        key=lambda e: e.timestamp or "9999-99-99",
    )

    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_memory(
    parsed: ParsedMemory,
    query: str,
    memory_type: str = "all",
    limit: int = 20,
) -> dict:
    """Full-text search across parsed memory entries.

    Returns results with relevance scoring based on:
    - Exact match presence
    - Match frequency
    - Position of first match (earlier = more relevant)

    Args:
        parsed: Previously parsed memory data.
        query: Search query string.
        memory_type: Filter by type ('all', 'episodic', 'semantic', 'user').
        limit: Maximum results to return.

    Returns:
        Dict with results, total count, and query metadata.
    """
    if not query:
        return {"results": [], "total": 0, "query": query, "memory_type": memory_type}

    query_lower = query.lower()
    query_terms = query_lower.split()
    scored_results: list[tuple[float, MemoryEntry, list[tuple[int, int]]]] = []

    for entry in parsed.entries:
        # Apply type filter
        if memory_type != "all" and entry.entry_type != memory_type:
            continue

        content_lower = entry.content.lower()

        # Check if any query term matches
        if not any(term in content_lower for term in query_terms):
            continue

        # Calculate relevance score
        score = 0.0
        highlights: list[tuple[int, int]] = []

        # Exact phrase match bonus
        if query_lower in content_lower:
            score += 0.5
            idx = content_lower.find(query_lower)
            highlights.append((idx, idx + len(query_lower)))

        # Term frequency scoring
        for term in query_terms:
            count = content_lower.count(term)
            score += min(count * 0.15, 0.3)  # Cap per-term contribution

            # Find highlight positions for individual terms
            start = 0
            while True:
                idx = content_lower.find(term, start)
                if idx == -1:
                    break
                highlights.append((idx, idx + len(term)))
                start = idx + 1

        # Position bonus (earlier matches = more relevant)
        first_pos = min(
            (content_lower.find(t) for t in query_terms if t in content_lower),
            default=len(content_lower),
        )
        position_score = max(0, 1.0 - (first_pos / max(len(content_lower), 1)))
        score += position_score * 0.2

        # Normalize to 0-1
        score = min(score, 1.0)

        # Deduplicate and sort highlights
        highlights = sorted(set(highlights))

        scored_results.append((score, entry, highlights))

    # Sort by relevance (descending)
    scored_results.sort(key=lambda x: x[0], reverse=True)

    # Build results with context
    results = []
    for score, entry, highlights in scored_results[:limit]:
        # Find surrounding entries for context
        idx = parsed.entries.index(entry)
        context_before = (
            parsed.entries[idx - 1].content
            if idx > 0
            else ""
        )
        context_after = (
            parsed.entries[idx + 1].content
            if idx < len(parsed.entries) - 1
            else ""
        )

        results.append({
            "source": entry.source,
            "section": entry.section,
            "content": entry.content,
            "timestamp": entry.timestamp,
            "relevance": round(score, 3),
            "context_before": context_before[:200],
            "context_after": context_after[:200],
            "highlights": highlights,
            "entry_type": entry.entry_type,
        })

    return {
        "results": results,
        "total": len(scored_results),
        "query": query,
        "memory_type": memory_type,
    }
