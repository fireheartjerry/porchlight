"""Consume Porchlight's own MCP server from a Strands agent.

With ``PORCHLIGHT_TOOLS=mcp`` the read-only data tools stop being Python imports and start being
MCP tools: locally the server is spawned as a stdio subprocess, and on AWS the same server sits
behind an AgentCore Gateway URL. The agents do not notice the difference.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from mcp import StdioServerParameters, stdio_client
from strands.tools.mcp import MCPClient

from ..config import Settings

SERVER_MODULE = "porchlight.mcp_server"

_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("PORCHLIGHT_MODE", "mode"),
    ("PORCHLIGHT_MODEL_PROVIDER", "model_provider"),
    ("PORCHLIGHT_STORE", "store"),
    ("PORCHLIGHT_SQLITE_PATH", "sqlite_path"),
    ("PORCHLIGHT_DYNAMO_TABLE", "dynamo_table"),
    ("PORCHLIGHT_AWS_REGION", "aws_region"),
    ("PORCHLIGHT_MEMORY_ID", "memory_id"),
    ("PORCHLIGHT_GROUP_NAME", "group_name"),
    ("PORCHLIGHT_TIMEZONE", "timezone"),
)


def server_env(settings: Settings, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the server subprocess so it opens the *same* data as the parent.

    ``PORCHLIGHT_TOOLS`` is forced back to ``local`` so the child never tries to spawn another
    MCP server of its own.
    """
    env = {key: str(value) for key, attr in _ENV_KEYS if (value := getattr(settings, attr, None)) is not None}
    env["PORCHLIGHT_TOOLS"] = "local"
    for passthrough in ("PATH", "HOME", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        if passthrough in os.environ:
            env[passthrough] = os.environ[passthrough]
    env.update(extra or {})
    return env


def make_mcp_tools(
    settings: Settings,
    *,
    python_executable: str | None = None,
    env: dict[str, str] | None = None,
    url: str | None = None,
    **client_kwargs: Any,
) -> MCPClient:
    """Build the ``MCPClient`` that serves Porchlight's read-only tools.

    Args:
        settings: Settings the server subprocess should run with.
        python_executable: Interpreter to spawn; defaults to the current one (the venv's).
        env: Extra environment variables for the subprocess.
        url: When set, connect to a remote MCP endpoint (AgentCore Gateway) instead of spawning
            a subprocess.
        **client_kwargs: Passed through to ``MCPClient`` (``startup_timeout``, ``prefix``, ...).

    Returns:
        A started-on-demand ``MCPClient``. It is a Strands ``ToolProvider``, so it can be handed
        straight to ``Agent(tools=[client])``; use it as a context manager (``with client:``) or
        call ``client.start()`` to hold the connection open.
    """
    if url:
        return MCPClient(url=url, **client_kwargs)
    params = StdioServerParameters(
        command=python_executable or sys.executable,
        args=["-m", SERVER_MODULE],
        env=server_env(settings, env),
    )
    return MCPClient(lambda: stdio_client(params), **client_kwargs)
