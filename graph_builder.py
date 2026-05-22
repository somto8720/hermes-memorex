"""Knowledge graph builder for hermes-memorex.

Extracts entities and relationships from parsed memory entries to
construct a graph suitable for D3.js force-directed visualization
and export to standard graph formats.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

from .memory_parser import MemoryEntry, ParsedMemory


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GraphNode:
    """A node in the knowledge graph."""

    id: str
    label: str
    type: str  # person, project, tool, concept
    mentions: int = 1
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @property
    def size(self) -> int:
        """Node size proportional to mention count."""
        return max(8, min(40, 8 + self.mentions * 2))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["size"] = self.size
        return d


@dataclass
class GraphEdge:
    """An edge in the knowledge graph."""

    source: str  # node id
    target: str  # node id
    label: str  # relationship type
    weight: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class KnowledgeGraph:
    """The complete knowledge graph."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        node_types = Counter(n.type for n in self.nodes)
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "stats": {
                "total_nodes": len(self.nodes),
                "total_edges": len(self.edges),
                "entity_types": dict(node_types),
            },
        }


# ---------------------------------------------------------------------------
# Entity extraction patterns
# ---------------------------------------------------------------------------

# Known programming languages, frameworks, and tools
_KNOWN_TOOLS = {
    "python", "javascript", "typescript", "rust", "go", "java", "c++", "c#",
    "ruby", "php", "swift", "kotlin", "scala", "elixir", "haskell", "lua",
    "react", "vue", "angular", "svelte", "next.js", "nextjs", "nuxt",
    "django", "flask", "fastapi", "express", "nest.js", "rails",
    "docker", "kubernetes", "terraform", "ansible", "jenkins", "github",
    "gitlab", "aws", "gcp", "azure", "vercel", "netlify", "heroku",
    "postgres", "postgresql", "mysql", "mongodb", "redis", "sqlite",
    "elasticsearch", "grafana", "prometheus", "nginx", "apache",
    "git", "npm", "pip", "cargo", "maven", "gradle", "webpack", "vite",
    "pytorch", "tensorflow", "jax", "numpy", "pandas", "scikit-learn",
    "langchain", "llamaindex", "openai", "anthropic", "hermes",
    "linux", "macos", "windows", "ubuntu", "debian", "arch",
    "vscode", "vim", "neovim", "emacs", "cursor", "obsidian",
    "d3.js", "d3", "three.js", "tailwind", "tailwindcss", "css",
    "html", "sql", "graphql", "rest", "grpc", "websocket",
}

# Relationship indicator patterns
_RELATIONSHIP_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(uses?|using|used)\b", re.I), "uses"),
    (re.compile(r"\b(prefers?|preferring|preferred|likes?)\b", re.I), "prefers"),
    (re.compile(r"\b(works?\s+(?:on|with)|working\s+(?:on|with))\b", re.I), "works_with"),
    (re.compile(r"\b(builds?|building|built)\b", re.I), "builds"),
    (re.compile(r"\b(deploys?|deploying|deployed)\b", re.I), "deploys"),
    (re.compile(r"\b(manages?|managing|managed)\b", re.I), "manages"),
    (re.compile(r"\b(depends?\s+on|requires?|requiring)\b", re.I), "depends_on"),
    (re.compile(r"\b(creates?|creating|created)\b", re.I), "creates"),
    (re.compile(r"\b(learns?|learning|learned|studied)\b", re.I), "learns"),
    (re.compile(r"\b(mentions?|mentioned|discusses?|discussed)\b", re.I), "mentions"),
    (re.compile(r"\b(integrates?\s+with|integrated)\b", re.I), "integrates_with"),
    (re.compile(r"\b(tests?|testing|tested)\b", re.I), "tests"),
    (re.compile(r"\b(debugs?|debugging|debugged|fixes?|fixing|fixed)\b", re.I), "debugs"),
    (re.compile(r"\b(asks?\s+about|asked\s+about|inquir\w+)\b", re.I), "asks_about"),
]


def _normalize_id(label: str) -> str:
    """Create a stable node ID from a label."""
    return re.sub(r"[^a-z0-9_]", "_", label.lower().strip()).strip("_")


def _extract_entities(text: str) -> list[tuple[str, str]]:
    """Extract entities from text, returning (label, type) tuples.

    Uses a combination of:
    - Known tool/tech matching (case-insensitive)
    - Capitalized word detection for names/projects
    - @mention detection
    - URL/path detection
    """
    entities: list[tuple[str, str]] = []
    text_lower = text.lower()
    words = re.findall(r"\b[\w.#+]+\b", text)

    # Match known tools
    for word in words:
        word_lower = word.lower().rstrip(".")
        if word_lower in _KNOWN_TOOLS:
            # Use proper casing from the known set or original text
            entities.append((word, "tool"))

    # Detect capitalized names (potential people or projects)
    # Match 2-3 capitalized words in sequence (e.g., "John Smith", "Hermes Agent")
    name_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
    for match in name_pattern.finditer(text):
        name = match.group(1)
        name_lower = name.lower()

        # Skip if it's a known tool (already captured)
        if name_lower in _KNOWN_TOOLS:
            continue

        # Skip common English words that happen to be capitalized
        skip_words = {
            "the", "this", "that", "these", "those", "here", "there",
            "when", "where", "what", "which", "who", "how", "why",
            "not", "but", "and", "for", "with", "from", "into",
            "about", "after", "before", "during", "between",
            "general", "episodic", "semantic", "memory", "user",
            "profile", "key", "facts", "learned", "preferences",
        }
        if all(w.lower() in skip_words for w in name.split()):
            continue

        # Heuristic: single capitalized words at sentence start are often
        # not entities, but multi-word sequences likely are
        if len(name.split()) >= 2:
            entities.append((name, "person"))
        elif name_lower not in skip_words:
            entities.append((name, "concept"))

    # @mentions
    for match in re.finditer(r"@(\w+)", text):
        entities.append((match.group(1), "person"))

    # Project-like patterns (e.g., my-project, some_app, SomeApp)
    project_pattern = re.compile(r"\b([a-z][\w]*[-_][\w-]+)\b")
    for match in project_pattern.finditer(text):
        name = match.group(1)
        if name.lower() not in _KNOWN_TOOLS and len(name) > 3:
            entities.append((name, "project"))

    return entities


def _extract_relationships(
    text: str, entities: list[tuple[str, str]]
) -> list[tuple[str, str, str]]:
    """Extract relationships between entities based on text context.

    Returns (source_label, target_label, relationship_type) tuples.
    """
    if len(entities) < 2:
        return []

    relationships: list[tuple[str, str, str]] = []

    # Find which relationship verbs appear in the text
    active_relations: list[str] = []
    for pattern, rel_type in _RELATIONSHIP_PATTERNS:
        if pattern.search(text):
            active_relations.append(rel_type)

    if not active_relations:
        active_relations = ["related_to"]

    # Create relationships between co-occurring entities
    # Use the first entity as the subject (heuristic)
    primary_rel = active_relations[0]
    for i, (label_a, _) in enumerate(entities):
        for label_b, _ in entities[i + 1 :]:
            if label_a.lower() != label_b.lower():
                relationships.append((label_a, label_b, primary_rel))

    return relationships


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(
    parsed: ParsedMemory,
    filter_type: str = "all",
    max_nodes: int = 100,
) -> KnowledgeGraph:
    """Build a knowledge graph from parsed memory entries.

    Args:
        parsed: ParsedMemory with extracted entries.
        filter_type: Filter nodes by type ('all', 'person', 'project',
                     'tool', 'concept').
        max_nodes: Maximum number of nodes in the output graph.

    Returns:
        KnowledgeGraph with nodes and edges.
    """
    # Accumulate entities across all entries
    node_map: dict[str, GraphNode] = {}
    edge_counter: dict[tuple[str, str, str], int] = Counter()

    for entry in parsed.entries:
        entities = _extract_entities(entry.content)

        for label, etype in entities:
            node_id = _normalize_id(label)
            if not node_id:
                continue

            if node_id in node_map:
                node = node_map[node_id]
                node.mentions += 1
                if entry.timestamp:
                    if node.first_seen is None or entry.timestamp < node.first_seen:
                        node.first_seen = entry.timestamp
                    if node.last_seen is None or entry.timestamp > node.last_seen:
                        node.last_seen = entry.timestamp
            else:
                node_map[node_id] = GraphNode(
                    id=node_id,
                    label=label,
                    type=etype,
                    mentions=1,
                    first_seen=entry.timestamp,
                    last_seen=entry.timestamp,
                    metadata={"context": entry.content[:150]},
                )

        # Extract relationships
        relationships = _extract_relationships(entry.content, entities)
        for src_label, tgt_label, rel_type in relationships:
            src_id = _normalize_id(src_label)
            tgt_id = _normalize_id(tgt_label)
            if src_id and tgt_id and src_id != tgt_id:
                edge_counter[(src_id, tgt_id, rel_type)] += 1

    # Apply type filter
    if filter_type != "all":
        node_map = {
            nid: node
            for nid, node in node_map.items()
            if node.type == filter_type
        }

    # Limit to top-N nodes by mention count
    sorted_nodes = sorted(
        node_map.values(), key=lambda n: n.mentions, reverse=True
    )[:max_nodes]
    kept_ids = {n.id for n in sorted_nodes}

    # Build edges (only between kept nodes)
    edges: list[GraphEdge] = []
    for (src, tgt, rel), weight in edge_counter.items():
        if src in kept_ids and tgt in kept_ids:
            edges.append(GraphEdge(source=src, target=tgt, label=rel, weight=weight))

    return KnowledgeGraph(nodes=sorted_nodes, edges=edges)


# ---------------------------------------------------------------------------
# Export functions
# ---------------------------------------------------------------------------

def export_json(graph: KnowledgeGraph) -> str:
    """Export graph as JSON."""
    return json.dumps(graph.to_dict(), indent=2)


def export_graphml(graph: KnowledgeGraph) -> str:
    """Export graph as GraphML for Gephi, yEd, etc."""
    root = ET.Element("graphml")
    root.set("xmlns", "http://graphml.graphstruct.org/xmlns")

    # Define attribute keys
    for attr in ["label", "type", "mentions", "size"]:
        key = ET.SubElement(root, "key")
        key.set("id", attr)
        key.set("for", "node")
        key.set("attr.name", attr)
        key.set("attr.type", "string" if attr in ("label", "type") else "int")

    edge_label_key = ET.SubElement(root, "key")
    edge_label_key.set("id", "label")
    edge_label_key.set("for", "edge")
    edge_label_key.set("attr.name", "label")
    edge_label_key.set("attr.type", "string")

    g = ET.SubElement(root, "graph")
    g.set("id", "memorex")
    g.set("edgedefault", "directed")

    for node in graph.nodes:
        n = ET.SubElement(g, "node")
        n.set("id", node.id)
        for attr, val in [
            ("label", node.label),
            ("type", node.type),
            ("mentions", str(node.mentions)),
            ("size", str(node.size)),
        ]:
            data = ET.SubElement(n, "data")
            data.set("key", attr)
            data.text = val

    for i, edge in enumerate(graph.edges):
        e = ET.SubElement(g, "edge")
        e.set("id", f"e{i}")
        e.set("source", edge.source)
        e.set("target", edge.target)
        data = ET.SubElement(e, "data")
        data.set("key", "label")
        data.text = edge.label

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def export_mermaid(graph: KnowledgeGraph) -> str:
    """Export graph as a Mermaid diagram."""
    lines = ["graph LR"]

    # Define node styles
    type_styles = {
        "person": ":::person",
        "project": ":::project",
        "tool": ":::tool",
        "concept": ":::concept",
    }

    for node in graph.nodes:
        style = type_styles.get(node.type, "")
        safe_label = node.label.replace('"', "'")
        lines.append(f'    {node.id}["{safe_label}"]{style}')

    for edge in graph.edges:
        safe_label = edge.label.replace('"', "'")
        lines.append(f'    {edge.source} -->|"{safe_label}"| {edge.target}')

    lines.extend([
        "",
        "    classDef person fill:#f59e0b,stroke:#d97706,color:#000",
        "    classDef project fill:#3b82f6,stroke:#2563eb,color:#fff",
        "    classDef tool fill:#10b981,stroke:#059669,color:#fff",
        "    classDef concept fill:#8b5cf6,stroke:#7c3aed,color:#fff",
    ])

    return "\n".join(lines)


def export_obsidian(graph: KnowledgeGraph) -> str:
    """Export graph as Obsidian-compatible markdown with wikilinks."""
    pages: list[str] = []

    for node in graph.nodes:
        page_lines = [
            f"# {node.label}",
            "",
            f"**Type:** {node.type}",
            f"**Mentions:** {node.mentions}",
        ]
        if node.first_seen:
            page_lines.append(f"**First seen:** {node.first_seen}")
        if node.last_seen:
            page_lines.append(f"**Last seen:** {node.last_seen}")

        # Find connections
        connections = []
        for edge in graph.edges:
            if edge.source == node.id:
                target_node = next(
                    (n for n in graph.nodes if n.id == edge.target), None
                )
                if target_node:
                    connections.append(
                        f"- {edge.label} → [[{target_node.label}]]"
                    )
            elif edge.target == node.id:
                source_node = next(
                    (n for n in graph.nodes if n.id == edge.source), None
                )
                if source_node:
                    connections.append(
                        f"- [[{source_node.label}]] → {edge.label}"
                    )

        if connections:
            page_lines.extend(["", "## Connections", ""])
            page_lines.extend(connections)

        if node.metadata.get("context"):
            page_lines.extend([
                "",
                "## Context",
                "",
                node.metadata["context"],
            ])

        pages.append("\n".join(page_lines))

    # Join all pages with a separator
    return "\n\n---\n\n".join(pages)


def export_graph(graph: KnowledgeGraph, fmt: str = "json") -> str:
    """Export graph in the specified format.

    Args:
        graph: The knowledge graph to export.
        fmt: One of 'json', 'graphml', 'mermaid', 'obsidian'.

    Returns:
        The exported graph as a string.
    """
    exporters = {
        "json": export_json,
        "graphml": export_graphml,
        "mermaid": export_mermaid,
        "obsidian": export_obsidian,
    }

    exporter = exporters.get(fmt)
    if exporter is None:
        raise ValueError(
            f"Unknown export format: {fmt!r}. "
            f"Supported: {', '.join(exporters)}"
        )

    return exporter(graph)
