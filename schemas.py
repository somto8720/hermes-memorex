"""Tool schemas for hermes-memorex plugin.

Defines the JSON schemas for the 5 tools exposed to the Hermes Agent LLM.
Each schema follows the OpenAI-compatible function-calling format.
"""

MEMOREX_DASHBOARD = {
    "name": "memorex_dashboard",
    "description": (
        "Launch the Memorex dashboard — a local web UI for exploring your agent's "
        "memory graph, skill evolution, and conversation history. "
        "Returns a URL you can open in your browser. "
        "Idempotent: if the dashboard is already running, returns the existing URL."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "port": {
                "type": "integer",
                "description": "Port to serve the dashboard on. Defaults to 7377.",
            }
        },
    },
}

MEMOREX_GRAPH = {
    "name": "memorex_graph",
    "description": (
        "Query your agent's knowledge graph. Parses memory files (MEMORY.md, USER.md, "
        "SQLite) and returns a graph of entities (people, projects, tools, concepts) "
        "and their relationships. Useful for understanding what the agent knows and "
        "how concepts are connected."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "filter_type": {
                "type": "string",
                "description": (
                    "Filter entities by type: 'person', 'project', 'tool', "
                    "'concept', or 'all'."
                ),
                "enum": ["all", "person", "project", "tool", "concept"],
            },
            "max_nodes": {
                "type": "integer",
                "description": "Maximum number of nodes to return. Defaults to 100.",
            },
        },
    },
}

MEMOREX_SKILLS = {
    "name": "memorex_skills",
    "description": (
        "Get a timeline of skill evolution. Reads the skills directory, "
        "tracks creation/modification history via git (if available), and "
        "includes Curator actions (pruning, consolidation). "
        "Shows how the agent's capabilities have grown over time."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": (
                    "Filter to a specific skill by name. Omit for all skills."
                ),
            },
            "include_diffs": {
                "type": "boolean",
                "description": (
                    "Include git diffs for each skill change. Defaults to false."
                ),
            },
        },
    },
}

MEMOREX_SEARCH = {
    "name": "memorex_search",
    "description": (
        "Search across the agent's memory. Full-text search through MEMORY.md, "
        "USER.md, and conversation history. Returns matching entries with context, "
        "timestamps, and relevance scoring."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string.",
            },
            "memory_type": {
                "type": "string",
                "description": (
                    "Filter by memory type: 'episodic', 'semantic', 'user', or 'all'."
                ),
                "enum": ["all", "episodic", "semantic", "user"],
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results. Defaults to 20.",
            },
        },
        "required": ["query"],
    },
}

MEMOREX_EXPORT = {
    "name": "memorex_export",
    "description": (
        "Export the knowledge graph in a standard format for use with external tools. "
        "Supported formats: JSON, GraphML, Mermaid diagram, or Obsidian-compatible "
        "markdown with wikilinks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": "Export format.",
                "enum": ["json", "graphml", "mermaid", "obsidian"],
            },
            "output_path": {
                "type": "string",
                "description": (
                    "File path to write the export to. "
                    "If omitted, returns the content directly."
                ),
            },
        },
    },
}

ALL_SCHEMAS = [
    MEMOREX_DASHBOARD,
    MEMOREX_GRAPH,
    MEMOREX_SKILLS,
    MEMOREX_SEARCH,
    MEMOREX_EXPORT,
]
