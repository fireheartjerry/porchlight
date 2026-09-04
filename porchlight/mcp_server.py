"""Porchlight's read-mostly data tools, exposed as an MCP server over stdio.

The same functions the in-process agents call are published here, so another agent — or Claude
Desktop, or an AgentCore Gateway — can ask "who could take this request?" without importing
Porchlight. Only read-only tools are exposed: nothing here sends a message, assigns a volunteer,
or closes a request.

Run it with ``python -m porchlight.mcp_server`` (see ``porchlight.tools.mcp_bridge``).
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from .config import Settings, get_settings
from .context import AppContext, build_context
from .tools import (
    find_candidates_impl,
    find_similar_open_requests_impl,
    lookup_requester_history_impl,
    query_log_impl,
    query_requests_impl,
    read_replies_impl,
    recall_memory_impl,
    volunteer_load_impl,
)

logger = logging.getLogger(__name__)

SERVER_NAME = "porchlight"
INSTRUCTIONS = (
    "Read-only access to a neighbourhood mutual-aid group's roster, requests, and quiet log. "
    "Use find_candidates to rank volunteers for a request, volunteer_load to check fairness, "
    "and recall_memory for durable notes about people."
)

_ctx: AppContext | None = None


def get_context(settings: Settings | None = None) -> AppContext:
    """Return the process-wide context, building it on first use.

    Built lazily so importing this module never opens a database or touches AWS.
    """
    global _ctx
    if _ctx is None:
        _ctx = build_context(settings or get_settings())
    return _ctx


def set_context(ctx: AppContext | None) -> None:
    """Override the process-wide context (tests, or an embedding host)."""
    global _ctx
    _ctx = ctx


def build_server(ctx: AppContext | None = None) -> FastMCP:
    """Build the MCP server, optionally bound to a specific context.

    Args:
        ctx: Context the tools read from; defaults to the lazily built process context.

    Returns:
        A configured :class:`FastMCP` server with the eight read-only Porchlight tools.
    """
    if ctx is not None:
        set_context(ctx)
    server = FastMCP(name=SERVER_NAME, instructions=INSTRUCTIONS)

    @server.tool()
    def lookup_requester_history(contact_or_name: str) -> dict:
        """Look up a requester and their recent requests by phone, email, or name.

        Returns {"requester": {...} | None, "recent_requests": [...]}; requester is null for a
        first-time requester.
        """
        return lookup_requester_history_impl(get_context(), contact_or_name, agent="mcp")

    @server.tool()
    def find_similar_open_requests(
        requester_id: str, category: str | None = None, window_hours: int = 72
    ) -> list[dict]:
        """Find open requests this neighbour already has on file, so a chase is not booked twice.

        Returns {request_id, summary, category, status, created_at, window_start,
        assigned_volunteer_id} dicts, newest first.
        """
        return find_similar_open_requests_impl(
            get_context(), requester_id, category, window_hours, agent="mcp"
        )

    @server.tool()
    def find_candidates(request_id: str, limit: int = 5) -> list[dict]:
        """Rank the volunteers who could take a request, best first.

        Scores skill fit, zone proximity, availability overlap, weekly fairness, follow-through,
        and remembered notes. Returns {volunteer_id, name, score, reasons, load_this_week,
        zones, skills, memory_notes} dicts.
        """
        return find_candidates_impl(get_context(), request_id, limit, agent="mcp")

    @server.tool()
    def volunteer_load(volunteer_id: str) -> dict:
        """How many jobs a volunteer has been on in the last seven days, and their weekly cap."""
        return volunteer_load_impl(get_context(), volunteer_id, agent="mcp")

    @server.tool()
    def query_requests(status: str | None = None, since_iso: str | None = None) -> list[dict]:
        """List aid requests, newest first, optionally filtered by status and creation time."""
        return query_requests_impl(get_context(), status, since_iso, agent="mcp")

    @server.tool()
    def query_log(
        request_id: str | None = None, since_iso: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Read the quiet log: everything Porchlight did, newest first."""
        return query_log_impl(get_context(), request_id, since_iso, limit, agent="mcp")

    @server.tool()
    def read_replies(request_id: str) -> list[dict]:
        """Read the volunteer replies that have arrived for a request, oldest first."""
        return read_replies_impl(get_context(), request_id, agent="mcp")

    @server.tool()
    def recall_memory(query: str, about: str | None = None) -> list[dict]:
        """Recall durable notes about a person or a kind of request from long-term memory."""
        return recall_memory_impl(get_context(), query, about, agent="mcp")

    return server


def main() -> None:
    """Serve the Porchlight tools over stdio."""
    logging.basicConfig(level=logging.WARNING)
    build_server().run("stdio")


if __name__ == "__main__":  # pragma: no cover - process entry point
    main()
