"""The MCP server and the client bridge, including a real stdio round trip."""

from __future__ import annotations

import json
import sys

import pytest
from a_helpers import FROZEN_NOW, make_ctx, make_request
from strands import Agent

from porchlight.clock import FrozenClock
from porchlight.config import Settings
from porchlight.mcp_server import SERVER_NAME, build_server, get_context, set_context
from porchlight.sim.fixtures import seed_store
from porchlight.store.sqlite_store import SqliteStore
from porchlight.testing.mock_model import MockModel, MockTurn
from porchlight.tools.mcp_bridge import SERVER_MODULE, make_mcp_tools, server_env

EXPECTED_TOOLS = {
    "lookup_requester_history",
    "find_similar_open_requests",
    "find_candidates",
    "volunteer_load",
    "query_requests",
    "query_log",
    "read_replies",
    "recall_memory",
}

REQUEST_ID = "req_mcp_demo"


@pytest.fixture
def seeded_db(tmp_path) -> str:
    """A real SQLite file with fixtures and one open request, for the subprocess to read."""
    path = str(tmp_path / "porchlight.db")
    clock = FrozenClock(FROZEN_NOW)
    store = SqliteStore(path)
    seed_store(store, clock)
    make_request(store, clock, request_id=REQUEST_ID)
    store.close()
    return path


@pytest.fixture
def subprocess_settings(seeded_db) -> Settings:
    return Settings(
        mode="demo",
        model_provider="mock",
        store="sqlite",
        tools="mcp",
        sqlite_path=seeded_db,
        timezone="America/Toronto",
    )


@pytest.fixture(autouse=True)
def _clear_server_context():
    yield
    set_context(None)


# --- server ---------------------------------------------------------------------------


async def test_the_server_publishes_exactly_the_read_only_tools(store, clock):
    server = build_server(make_ctx(store, clock))
    tools = await server.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description and len(tool.description) > 20


async def test_no_side_effecting_tool_is_published(store, clock):
    tools = await build_server(make_ctx(store, clock)).list_tools()
    names = {t.name for t in tools}
    assert names.isdisjoint({"send_message", "assign_volunteer", "close_request", "remember"})


async def test_server_tools_read_the_bound_context(store, clock):
    ctx = make_ctx(store, clock)
    request = make_request(store, clock)
    server = build_server(ctx)
    blocks, structured = await server.call_tool("find_candidates", {"request_id": request.id, "limit": 2})
    assert [json.loads(block.text) for block in blocks] == structured["result"]
    candidates = structured["result"]
    assert len(candidates) == 2
    assert candidates[0]["reasons"]
    assert candidates[0]["score"] >= candidates[1]["score"]


def test_set_context_overrides_the_lazy_default(store, clock):
    ctx = make_ctx(store, clock)
    set_context(ctx)
    assert get_context() is ctx


# --- bridge configuration -------------------------------------------------------------


def test_server_env_carries_the_settings_and_forces_local_tools(subprocess_settings, seeded_db):
    env = server_env(subprocess_settings)
    assert env["PORCHLIGHT_SQLITE_PATH"] == seeded_db
    assert env["PORCHLIGHT_STORE"] == "sqlite"
    assert env["PORCHLIGHT_MODEL_PROVIDER"] == "mock"
    assert env["PORCHLIGHT_TOOLS"] == "local"
    assert "PATH" in env


def test_server_env_accepts_extras(subprocess_settings):
    env = server_env(subprocess_settings, {"PORCHLIGHT_MODE": "live", "EXTRA": "1"})
    assert env["PORCHLIGHT_MODE"] == "live"
    assert env["EXTRA"] == "1"


def test_make_mcp_tools_defaults_to_this_interpreter(subprocess_settings):
    client = make_mcp_tools(subprocess_settings)
    assert client is not None
    assert SERVER_MODULE == "porchlight.mcp_server"


def test_a_url_builds_a_remote_client(subprocess_settings):
    client = make_mcp_tools(subprocess_settings, url="https://gateway.example/mcp")
    assert client is not None


# --- real stdio round trip ------------------------------------------------------------


def test_real_stdio_round_trip_lists_and_calls_tools(subprocess_settings):
    client = make_mcp_tools(subprocess_settings, python_executable=sys.executable)
    with client:
        tools = client.list_tools_sync()
        assert {t.tool_name for t in tools} == EXPECTED_TOOLS

        result = client.call_tool_sync("mcp-1", "find_candidates", {"request_id": REQUEST_ID, "limit": 3})
        assert result["status"] == "success"
        candidates = [json.loads(block["text"]) for block in result["content"]]
        assert 1 <= len(candidates) <= 3
        assert candidates[0]["score"] >= candidates[-1]["score"]
        assert candidates[0]["reasons"]

        history = client.call_tool_sync(
            "mcp-2", "lookup_requester_history", {"contact_or_name": "+1-555-0201"}
        )
        assert history["status"] == "success"


def test_an_agent_can_use_the_mcp_tools(subprocess_settings):
    """The client is a ToolProvider, so the agent starts and stops the server itself."""
    client = make_mcp_tools(subprocess_settings, python_executable=sys.executable)
    model = MockModel(
        script=[
            MockTurn(tool_calls=[("volunteer_load", {"volunteer_id": "vol_maria"})]),
            MockTurn(text="Maria has room this week."),
        ],
        default_structured=False,
    )
    agent = Agent(
        model=model,
        tools=[client],
        system_prompt="You are Porchlight's matcher.",
        name="matcher",
        callback_handler=None,
    )
    try:
        result = agent("How busy is Maria?")
        assert result.stop_reason == "end_turn"
        assert "volunteer_load" in agent.tool_names
        texts = [
            block["toolResult"]["content"][0]["text"]
            for message in agent.messages
            for block in message.get("content", [])
            if "toolResult" in block
        ]
        assert texts and "max_per_week" in texts[0]
    finally:
        client.stop(None, None, None)


def test_the_server_name_is_stable(subprocess_settings):
    assert SERVER_NAME == "porchlight"
