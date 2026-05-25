# 🧠 hermes-memorex

**Memory Explorer & Knowledge Graph Visualizer for [Hermes Agent](https://github.com/NousResearch/hermes-agent)**

> Visualize what your agent knows, how its skills evolve, and search across its entire memory — all from a stunning local dashboard.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-brightgreen.svg)](#zero-dependencies)

---

## Why Memorex?

Hermes Agent builds a rich internal world model — episodic memories, semantic facts, user profiles, and learned skills. But there's been **no way to see it**. Until now.

**hermes-memorex** fills a [confirmed ecosystem gap](https://github.com/NousResearch/hermes-agent/issues/346) by providing:

| Feature | Description |
|---|---|
| 🕸️ **Knowledge Graph** | Interactive D3.js force-directed graph of entities and relationships |
| 📈 **Skill Evolution** | Timeline of skill creation, modification, and Curator actions |
| 🔍 **Memory Search** | Full-text search across all memory with relevance scoring |
| 📤 **Export** | JSON, GraphML, Mermaid, and Obsidian-compatible formats |

## Quick Start

### Option 1: Drop-in Plugin (Recommended)

```bash
# Copy the plugin to your Hermes plugins directory
cp -r hermes-memorex ~/.hermes/plugins/hermes-memorex

# Enable it
hermes plugins enable hermes-memorex
```

### Option 2: pip Install

```bash
pip install .

# Or directly from GitHub
pip install git+https://github.com/somto8720/hermes-memorex.git
```

### Launch the Dashboard

Once installed, simply ask your agent:

```
> Open the Memorex dashboard
```

Or call the tool directly:

```
> /tool memorex_dashboard
```

The agent will start a local server and return a URL (default: `http://localhost:7377`).

## Dashboard

### Knowledge Graph

Interactive force-directed graph visualization:

- **Nodes** colored by entity type (person, project, tool, concept)
- **Node size** proportional to mention frequency
- **Edges** with relationship labels and directional arrows
- **Zoom/pan** with mouse wheel and drag
- **Click** any node for a detail panel with metadata and connections
- **Filter** by entity type, search for specific nodes
- **Drag** nodes to rearrange the layout

### Skill Evolution

Timeline of how your agent's capabilities have grown:

- **Chronological timeline** with color-coded event types
- **Curator summary** — retained, pruned, and consolidated skill counts
- **Diff viewer** — see exactly what changed in each skill revision
- **Agent-authored badges** for skills the agent created itself

### Memory Search

Full-text search across all memory sources:

- **Relevance scoring** with highlighted matches
- **Filter** by memory type (episodic, semantic, user)
- **Context** — see what comes before and after each match
- **Source badges** showing which file the memory came from

## Tools

hermes-memorex registers 5 tools with the agent:

| Tool | Description |
|---|---|
| `memorex_dashboard` | Launch the web dashboard (idempotent) |
| `memorex_graph` | Query the knowledge graph as JSON |
| `memorex_skills` | Get skill evolution timeline |
| `memorex_search` | Search across all memory |
| `memorex_export` | Export graph to JSON, GraphML, Mermaid, or Obsidian |

### Example: Export to Obsidian

```
> Export my knowledge graph to Obsidian format and save it to ~/notes/hermes-graph.md
```

The agent will call `memorex_export` with `format=obsidian` and generate markdown with `[[wikilinks]]` that Obsidian's graph view can visualize.

## Architecture

```
hermes-memorex/
├── plugin.yaml            # Plugin manifest
├── __init__.py            # Registration entry point
├── schemas.py             # 5 tool schemas (OpenAI function-calling format)
├── tools.py               # Tool handlers
├── server.py              # Local HTTP server (stdlib, daemon thread)
├── memory_parser.py       # Parses MEMORY.md, USER.md, SQLite
├── skill_tracker.py       # Git history + Curator log parsing
├── graph_builder.py       # Entity extraction + graph construction
├── static/
│   ├── index.html         # Dashboard SPA
│   ├── style.css          # Dark-mode glassmorphism theme
│   └── app.js             # D3.js visualization + interactivity
├── tests/
│   ├── test_memory_parser.py
│   ├── test_graph_builder.py
│   └── test_skill_tracker.py
├── pyproject.toml         # pip-installable with entry points
├── LICENSE                # MIT
└── README.md              # This file
```

### Design Decisions

- **Zero external dependencies** — stdlib only (Python 3.10+). D3.js loaded via CDN in the frontend.
- **No database required** — reads directly from Hermes' existing memory files.
- **Daemon thread server** — doesn't block the agent; runs silently in the background.
- **Response caching** — 30-second TTL prevents redundant re-parsing on rapid API calls.
- **Graceful degradation** — works with or without git, with or without Curator logs, with or without SQLite.

## Zero Dependencies

hermes-memorex uses **only the Python standard library**. No pip installs needed beyond Hermes itself. The frontend loads D3.js v7 from CDN.

This is intentional — a plugin shouldn't force dependency conflicts on your agent's runtime.

## Development

### Run Tests

```bash
# From the project root
python -m pytest tests/ -v
```

### Project Structure for Contributors

- `memory_parser.py` — Start here to understand how memory files are read
- `graph_builder.py` — Entity extraction logic and export formats
- `skill_tracker.py` — Git and Curator integration
- `server.py` — HTTP server and API endpoints
- `tools.py` — Thin wrappers connecting schemas to modules

### Adding a New Export Format

1. Add a function `export_yourformat(graph: KnowledgeGraph) -> str` in `graph_builder.py`
2. Add it to the `exporters` dict in `export_graph()`
3. Add the format to `MEMOREX_EXPORT` schema's enum in `schemas.py`
4. Add a content type mapping in `server.py`'s `_handle_export()`

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/amazing-feature`)
3. Write tests for new functionality
4. Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, etc.)
5. Open a PR with a clear description

## License

MIT — see [LICENSE](LICENSE).

---

Built for the [Hermes Agent](https://github.com/NousResearch/hermes-agent) ecosystem by [Nous Research](https://nousresearch.com) community contributors. 🚀
