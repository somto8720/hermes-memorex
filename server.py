"""Local HTTP server for the hermes-memorex dashboard.

Serves the static frontend and provides API endpoints for the
dashboard to consume. Runs in a background daemon thread so it
doesn't block the agent.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

from .memory_parser import parse_all_memory, search_memory, ParsedMemory
from .graph_builder import build_graph, export_graph
from .skill_tracker import track_skills


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_server_instance: Optional[HTTPServer] = None
_server_thread: Optional[threading.Thread] = None
_start_time: float = 0
_hermes_dir: Optional[str] = None

# Cache parsed data to avoid re-parsing on every request
_cache: dict[str, Any] = {}
_cache_ts: float = 0
_CACHE_TTL = 30  # seconds


def _get_parsed_memory() -> ParsedMemory:
    """Get parsed memory with caching."""
    global _cache, _cache_ts
    now = time.time()
    if "memory" not in _cache or (now - _cache_ts) > _CACHE_TTL:
        _cache["memory"] = parse_all_memory(_hermes_dir)
        _cache_ts = now
    return _cache["memory"]


def _invalidate_cache():
    """Force cache refresh on next request."""
    global _cache, _cache_ts
    _cache.clear()
    _cache_ts = 0


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class MemoRexHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Memorex dashboard."""

    # Suppress default logging to stderr
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str = "text/plain") -> None:
        """Send a plain text response."""
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath: Path) -> None:
        """Serve a static file."""
        if not filepath.exists():
            self.send_error(404, f"File not found: {filepath.name}")
            return

        content_type, _ = mimetypes.guess_type(str(filepath))
        if content_type is None:
            content_type = "application/octet-stream"

        try:
            body = filepath.read_bytes()
        except OSError:
            self.send_error(500, "Failed to read file")
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # API routes
        if path == "/api/status":
            self._handle_status()
        elif path == "/api/graph":
            self._handle_graph(params)
        elif path == "/api/skills":
            self._handle_skills(params)
        elif path == "/api/search":
            self._handle_search(params)
        elif path == "/api/export":
            self._handle_export(params)
        else:
            # Static file serving
            self._handle_static(path)

    def _handle_status(self) -> None:
        """Return server status."""
        parsed = _get_parsed_memory()
        skills = track_skills(_hermes_dir)
        graph = build_graph(parsed)

        self._send_json({
            "version": "1.0.0",
            "memory_files": len(parsed.sources),
            "skill_count": len(skills.skills),
            "entity_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "uptime_seconds": int(time.time() - _start_time),
        })

    def _handle_graph(self, params: dict) -> None:
        """Return the knowledge graph."""
        parsed = _get_parsed_memory()
        filter_type = params.get("filter_type", ["all"])[0]
        max_nodes = int(params.get("max_nodes", ["100"])[0])

        graph = build_graph(parsed, filter_type=filter_type, max_nodes=max_nodes)
        self._send_json(graph.to_dict())

    def _handle_skills(self, params: dict) -> None:
        """Return skill evolution data."""
        skill_name = params.get("skill_name", [None])[0]
        include_diffs = params.get("include_diffs", ["false"])[0].lower() == "true"

        evolution = track_skills(
            _hermes_dir,
            skill_name=skill_name,
            include_diffs=include_diffs,
        )
        self._send_json(evolution.to_dict())

    def _handle_search(self, params: dict) -> None:
        """Search memory entries."""
        query = params.get("q", [""])[0]
        memory_type = params.get("type", ["all"])[0]
        limit = int(params.get("limit", ["20"])[0])

        if not query:
            self._send_json(
                {"error": "Missing required parameter: q"}, status=400
            )
            return

        parsed = _get_parsed_memory()
        results = search_memory(parsed, query, memory_type=memory_type, limit=limit)
        self._send_json(results)

    def _handle_export(self, params: dict) -> None:
        """Export the knowledge graph."""
        fmt = params.get("format", ["json"])[0]
        parsed = _get_parsed_memory()
        graph = build_graph(parsed)

        try:
            content = export_graph(graph, fmt)
        except ValueError as e:
            self._send_json({"error": str(e)}, status=400)
            return

        content_types = {
            "json": "application/json",
            "graphml": "application/xml",
            "mermaid": "text/plain",
            "obsidian": "text/markdown",
        }

        self._send_text(content, content_types.get(fmt, "text/plain"))

    def _handle_static(self, path: str) -> None:
        """Serve static files from the static/ directory."""
        static_dir = Path(__file__).parent / "static"

        if path in ("", "/"):
            filepath = static_dir / "index.html"
        else:
            # Sanitize path to prevent directory traversal
            clean = path.lstrip("/")
            if ".." in clean:
                self.send_error(403, "Forbidden")
                return
            filepath = static_dir / clean

        self._send_file(filepath)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def start_server(port: int = 7377, hermes_dir: Optional[str] = None) -> str:
    """Start the Memorex dashboard server in a background thread.

    Args:
        port: Port to listen on.
        hermes_dir: Override Hermes home directory path.

    Returns:
        The URL where the dashboard is accessible.
    """
    global _server_instance, _server_thread, _start_time, _hermes_dir

    _hermes_dir = hermes_dir

    # If already running, return existing URL
    if _server_instance is not None:
        addr = _server_instance.server_address
        return f"http://localhost:{addr[1]}"

    _invalidate_cache()
    _start_time = time.time()

    _server_instance = HTTPServer(("127.0.0.1", port), MemoRexHandler)
    _server_thread = threading.Thread(
        target=_server_instance.serve_forever,
        daemon=True,
        name="memorex-dashboard",
    )
    _server_thread.start()

    return f"http://localhost:{port}"


def stop_server() -> None:
    """Stop the Memorex dashboard server."""
    global _server_instance, _server_thread

    if _server_instance is not None:
        _server_instance.shutdown()
        _server_instance = None
        _server_thread = None
        _invalidate_cache()


def is_running() -> bool:
    """Check if the server is currently running."""
    return _server_instance is not None
