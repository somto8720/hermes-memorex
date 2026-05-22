"""Tool handlers for hermes-memorex.

Each function is registered as a Hermes Agent tool via ctx.register_tool().
Handlers receive the LLM's arguments dict and return a JSON string result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .server import start_server, is_running
from .memory_parser import parse_all_memory, search_memory
from .graph_builder import build_graph, export_graph
from .skill_tracker import track_skills


def handle_memorex_dashboard(args: dict[str, Any], **kwargs: Any) -> str:
    """Launch or connect to the Memorex dashboard.

    Starts a local HTTP server serving the knowledge graph visualizer,
    skill evolution timeline, and memory search interface.
    """
    port = args.get("port", 7377)

    if is_running():
        url = f"http://localhost:{port}"
        return json.dumps({
            "status": "already_running",
            "url": url,
            "message": f"Memorex dashboard is already running at {url}",
        })

    try:
        url = start_server(port=port)
        return json.dumps({
            "status": "started",
            "url": url,
            "message": (
                f"Memorex dashboard started at {url}\n"
                "Open this URL in your browser to explore your memory graph, "
                "skill evolution, and search your agent's memory."
            ),
        })
    except OSError as e:
        return json.dumps({
            "status": "error",
            "message": f"Failed to start dashboard: {e}",
        })


def handle_memorex_graph(args: dict[str, Any], **kwargs: Any) -> str:
    """Query the agent's knowledge graph.

    Parses memory files and returns a graph of entities and relationships.
    """
    filter_type = args.get("filter_type", "all")
    max_nodes = args.get("max_nodes", 100)

    parsed = parse_all_memory()
    graph = build_graph(parsed, filter_type=filter_type, max_nodes=max_nodes)
    data = graph.to_dict()

    # Add a human-readable summary
    stats = data["stats"]
    type_summary = ", ".join(
        f"{count} {t}{'s' if count != 1 else ''}"
        for t, count in stats["entity_types"].items()
    )
    data["summary"] = (
        f"Knowledge graph: {stats['total_nodes']} entities "
        f"({type_summary}) with {stats['total_edges']} relationships."
    )

    return json.dumps(data, indent=2)


def handle_memorex_skills(args: dict[str, Any], **kwargs: Any) -> str:
    """Get the skill evolution timeline.

    Reads skills directory, git history, and Curator logs.
    """
    skill_name = args.get("skill_name")
    include_diffs = args.get("include_diffs", False)

    evolution = track_skills(
        skill_name=skill_name,
        include_diffs=include_diffs,
    )
    data = evolution.to_dict()

    # Add human-readable summary
    n_skills = len(data["skills"])
    curator = data["curator_summary"]
    data["summary"] = (
        f"Tracking {n_skills} skill{'s' if n_skills != 1 else ''}. "
        f"Curator has run {curator.get('total_runs', 0)} time(s): "
        f"{curator.get('skills_retained', 0)} retained, "
        f"{curator.get('skills_pruned', 0)} pruned, "
        f"{curator.get('skills_consolidated', 0)} consolidated."
    )

    return json.dumps(data, indent=2)


def handle_memorex_search(args: dict[str, Any], **kwargs: Any) -> str:
    """Search across the agent's memory.

    Full-text search with relevance scoring and context.
    """
    query = args.get("query", "")
    memory_type = args.get("memory_type", "all")
    limit = args.get("limit", 20)

    if not query:
        return json.dumps({
            "error": "A search query is required.",
            "results": [],
            "total": 0,
        })

    parsed = parse_all_memory()
    results = search_memory(parsed, query, memory_type=memory_type, limit=limit)

    # Add summary
    results["summary"] = (
        f"Found {results['total']} result{'s' if results['total'] != 1 else ''} "
        f"for '{query}'"
        + (f" (filtered to {memory_type})" if memory_type != "all" else "")
        + f". Showing top {min(limit, results['total'])}."
    )

    return json.dumps(results, indent=2)


def handle_memorex_export(args: dict[str, Any], **kwargs: Any) -> str:
    """Export the knowledge graph in a standard format.

    Supports JSON, GraphML, Mermaid, and Obsidian-compatible markdown.
    """
    fmt = args.get("format", "json")
    output_path = args.get("output_path")

    parsed = parse_all_memory()
    graph = build_graph(parsed)

    try:
        content = export_graph(graph, fmt)
    except ValueError as e:
        return json.dumps({"error": str(e)})

    if output_path:
        try:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content, encoding="utf-8")
            return json.dumps({
                "status": "exported",
                "format": fmt,
                "path": str(out),
                "message": f"Knowledge graph exported to {out} in {fmt} format.",
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
            })
        except OSError as e:
            return json.dumps({
                "status": "error",
                "message": f"Failed to write export file: {e}",
            })

    # Return content inline (truncated if very large)
    if len(content) > 50_000:
        return json.dumps({
            "status": "exported",
            "format": fmt,
            "message": (
                f"Export is {len(content)} characters. "
                "Use output_path to save to a file instead."
            ),
            "preview": content[:5000] + "\n...(truncated)",
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        })

    return json.dumps({
        "status": "exported",
        "format": fmt,
        "content": content,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
    })
