"""Porchlight's tool surface.

Every tool is declared with ``@tool(context=True)`` and reads its
:class:`~porchlight.context.AppContext` from ``tool_context.invocation_state["ctx"]``. Return
values are plain JSON-serializable dicts, lists, or strings so they round-trip through the model
and through the MCP server unchanged.

Each tool is a thin wrapper around an ``*_impl`` function that takes the context explicitly.
:mod:`porchlight.mcp_server` calls those directly, which is why the MCP surface and the in-process
surface can never disagree.

Names, signatures, and the tool groups are fixed by ``docs/CONTRACTS.md`` §6.
"""

from __future__ import annotations

from .intake import lookup_requester_history, lookup_requester_history_impl
from .matching import (
    find_candidates,
    find_candidates_impl,
    volunteer_load,
    volunteer_load_impl,
)
from .messaging import (
    read_replies,
    read_replies_impl,
    schedule_message,
    schedule_message_impl,
    send_message,
    send_message_impl,
)
from .records import (
    assign_volunteer,
    assign_volunteer_impl,
    close_request,
    close_request_impl,
    query_log,
    query_log_impl,
    query_requests,
    query_requests_impl,
    recall_memory,
    recall_memory_impl,
    record_attempt,
    record_attempt_impl,
    remember,
    remember_impl,
    update_request,
    update_request_impl,
)

__all__ = [
    "ALL_TOOLS",
    "BRIEF_TOOLS",
    "INTAKE_TOOLS",
    "MATCHER_TOOLS",
    "OUTREACH_TOOLS",
    "READ_ONLY_TOOLS",
    "SIDE_EFFECT_TOOLS",
    "STEWARD_TOOLS",
    "assign_volunteer",
    "assign_volunteer_impl",
    "close_request",
    "close_request_impl",
    "find_candidates",
    "find_candidates_impl",
    "lookup_requester_history",
    "lookup_requester_history_impl",
    "query_log",
    "query_log_impl",
    "query_requests",
    "query_requests_impl",
    "read_replies",
    "read_replies_impl",
    "recall_memory",
    "recall_memory_impl",
    "record_attempt",
    "record_attempt_impl",
    "remember",
    "remember_impl",
    "schedule_message",
    "schedule_message_impl",
    "send_message",
    "send_message_impl",
    "update_request",
    "update_request_impl",
    "volunteer_load",
    "volunteer_load_impl",
]

# --------------------------------------------------------------------------------------
# Tool groups (per agent)
# --------------------------------------------------------------------------------------

INTAKE_TOOLS = [lookup_requester_history, update_request]
MATCHER_TOOLS = [find_candidates, volunteer_load, recall_memory]
OUTREACH_TOOLS = [send_message, read_replies, assign_volunteer, record_attempt, schedule_message]
STEWARD_TOOLS = [send_message, schedule_message, remember, close_request, update_request]
BRIEF_TOOLS = [query_requests, query_log]

ALL_TOOLS = [
    lookup_requester_history,
    find_candidates,
    volunteer_load,
    recall_memory,
    remember,
    send_message,
    schedule_message,
    read_replies,
    assign_volunteer,
    record_attempt,
    update_request,
    close_request,
    query_requests,
    query_log,
]

SIDE_EFFECT_TOOLS = [send_message, schedule_message, assign_volunteer, close_request, remember]
"""Tools the policy engine gates (``docs/CONTRACTS.md`` §6)."""

READ_ONLY_TOOLS = [
    lookup_requester_history,
    find_candidates,
    volunteer_load,
    recall_memory,
    read_replies,
    query_requests,
    query_log,
]
"""Tools with no side effects; these are the ones exposed over MCP."""
