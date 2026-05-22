"""hermes-memorex — Memory Explorer & Knowledge Graph Visualizer.

Plugin registration entry point. Called by Hermes Agent at startup
to wire tool schemas to their handler functions.
"""

from .schemas import (
    MEMOREX_DASHBOARD,
    MEMOREX_GRAPH,
    MEMOREX_SKILLS,
    MEMOREX_SEARCH,
    MEMOREX_EXPORT,
)
from .tools import (
    handle_memorex_dashboard,
    handle_memorex_graph,
    handle_memorex_skills,
    handle_memorex_search,
    handle_memorex_export,
)


def register(ctx):
    """Register all Memorex tools with the Hermes Agent context.

    Args:
        ctx: The Hermes plugin context object providing registration methods.
    """
    ctx.register_tool(MEMOREX_DASHBOARD, handle_memorex_dashboard)
    ctx.register_tool(MEMOREX_GRAPH, handle_memorex_graph)
    ctx.register_tool(MEMOREX_SKILLS, handle_memorex_skills)
    ctx.register_tool(MEMOREX_SEARCH, handle_memorex_search)
    ctx.register_tool(MEMOREX_EXPORT, handle_memorex_export)
