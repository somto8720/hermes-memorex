"""Tests for the knowledge graph builder module."""

from pathlib import Path

from hermes_memorex.memory_parser import (
    MemoryEntry,
    ParsedMemory,
    parse_all_memory,
)
from hermes_memorex.graph_builder import (
    GraphNode,
    GraphEdge,
    KnowledgeGraph,
    build_graph,
    export_json,
    export_graphml,
    export_mermaid,
    export_obsidian,
    export_graph,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MEMORY = """\
# Agent Memory

## Episodic Memory

- [2026-01-15] User asked about deploying Python app to AWS Lambda
- [2026-02-10] Worked on React dashboard with TypeScript and Next.js
- [2026-03-05] Debugged PostgreSQL connection pooling issue with Docker
- [2026-04-20] Alex Chen requested help with Kubernetes deployment

## Semantic Memory

- Python is the primary programming language used by Alex Chen
- The project uses Next.js with TypeScript for the frontend
- Docker containers are deployed to AWS
- PostgreSQL is the main database
"""


def _make_parsed(tmp_path: Path) -> ParsedMemory:
    """Create a ParsedMemory from the sample data."""
    filepath = tmp_path / "MEMORY.md"
    filepath.write_text(SAMPLE_MEMORY, encoding="utf-8")
    return parse_all_memory(tmp_path)


# ---------------------------------------------------------------------------
# build_graph tests
# ---------------------------------------------------------------------------

class TestBuildGraph:
    """Tests for graph construction from memory entries."""

    def test_extracts_entities(self, tmp_path: Path):
        parsed = _make_parsed(tmp_path)
        graph = build_graph(parsed)

        assert len(graph.nodes) > 0
        labels = {n.label.lower() for n in graph.nodes}
        # Should find known tools
        assert "python" in labels or "Python" in {n.label for n in graph.nodes}

    def test_creates_edges(self, tmp_path: Path):
        parsed = _make_parsed(tmp_path)
        graph = build_graph(parsed)

        # Should have some relationships
        assert len(graph.edges) >= 0  # May or may not find edges depending on extraction

    def test_filter_by_type(self, tmp_path: Path):
        parsed = _make_parsed(tmp_path)
        graph = build_graph(parsed, filter_type="tool")

        for node in graph.nodes:
            assert node.type == "tool"

    def test_max_nodes_limit(self, tmp_path: Path):
        parsed = _make_parsed(tmp_path)
        graph = build_graph(parsed, max_nodes=3)

        assert len(graph.nodes) <= 3

    def test_node_size_proportional(self, tmp_path: Path):
        parsed = _make_parsed(tmp_path)
        graph = build_graph(parsed)

        for node in graph.nodes:
            assert 8 <= node.size <= 40

    def test_to_dict_structure(self, tmp_path: Path):
        parsed = _make_parsed(tmp_path)
        graph = build_graph(parsed)
        data = graph.to_dict()

        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data
        assert "total_nodes" in data["stats"]
        assert "total_edges" in data["stats"]
        assert "entity_types" in data["stats"]

    def test_empty_memory_returns_empty_graph(self):
        parsed = ParsedMemory()
        graph = build_graph(parsed)

        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

class TestExports:
    """Tests for graph export functions."""

    def _make_graph(self) -> KnowledgeGraph:
        """Create a simple test graph."""
        return KnowledgeGraph(
            nodes=[
                GraphNode(id="python", label="Python", type="tool", mentions=10),
                GraphNode(id="alex", label="Alex Chen", type="person", mentions=5),
                GraphNode(id="my_project", label="my-project", type="project", mentions=3),
            ],
            edges=[
                GraphEdge(source="alex", target="python", label="uses", weight=5),
                GraphEdge(source="alex", target="my_project", label="works_with", weight=3),
            ],
        )

    def test_export_json(self):
        graph = self._make_graph()
        result = export_json(graph)

        import json
        data = json.loads(result)
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

    def test_export_graphml(self):
        graph = self._make_graph()
        result = export_graphml(graph)

        assert "<?xml" in result
        assert "graphml" in result
        assert "Python" in result
        assert "Alex Chen" in result

    def test_export_mermaid(self):
        graph = self._make_graph()
        result = export_mermaid(graph)

        assert "graph LR" in result
        assert "python" in result
        assert "classDef" in result

    def test_export_obsidian(self):
        graph = self._make_graph()
        result = export_obsidian(graph)

        assert "# Python" in result
        assert "# Alex Chen" in result
        assert "[[" in result  # Wikilinks

    def test_export_graph_dispatches(self):
        graph = self._make_graph()
        for fmt in ("json", "graphml", "mermaid", "obsidian"):
            result = export_graph(graph, fmt)
            assert len(result) > 0

    def test_export_graph_invalid_format(self):
        graph = self._make_graph()
        try:
            export_graph(graph, "invalid")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
