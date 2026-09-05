"""Long-term memory: the SQLite store, the AgentCore store, and the Strands wiring."""

from __future__ import annotations

import asyncio

import pytest
from a_helpers import make_ctx
from strands import Agent
from strands.memory import MemoryManager
from strands.memory.types import MemoryEntry

from porchlight.config import Settings
from porchlight.memory import (
    AgentCoreMemoryStore,
    SqliteMemoryStore,
    add_memory,
    entry_to_dict,
    make_memory_store,
    run_sync,
    search_memory,
)
from porchlight.memory.manager import make_memory_manager
from porchlight.testing.mock_model import MockModel

NOTES = [
    ("Mr. Okafor asks for Maria by name for his dialysis rides.", "vol_maria", "preference"),
    ("Devon only does weekends; he has a pickup truck.", "vol_devon", "preference"),
    ("Priya set up three tablets on Sunday afternoons.", "vol_priya", "outcome"),
    ("The Bell family needs the walk cleared before 7am in winter.", "rqr_bell", "fact"),
]


@pytest.fixture
def memory(clock) -> SqliteMemoryStore:
    store = SqliteMemoryStore(":memory:", clock=clock)
    for content, about_id, kind in NOTES:
        store.add_sync(content, {"about_id": about_id, "kind": kind})
    yield store
    store.close()


# --- protocol conformance -------------------------------------------------------------


def test_sqlite_store_exposes_the_memory_store_fields(memory):
    assert memory.name == "porchlight_memory"
    assert isinstance(memory.description, str) and memory.description
    assert memory.max_search_results == 5
    assert memory.writable is True
    assert memory.extraction is False
    for method in ("search", "add", "add_messages", "initialize"):
        assert callable(getattr(memory, method))


async def test_async_api_matches_the_sync_twins(memory):
    await memory.initialize()
    entry_id = await memory.add("Hank is unfazed by hospital parking.", {"about_id": "vol_hank"})
    assert entry_id.startswith("mem_")
    hits = await memory.search("hospital parking")
    assert hits and isinstance(hits[0], MemoryEntry)
    assert hits[0].store_name == "porchlight_memory"


async def test_search_options_are_honoured(memory):
    scoped = await memory.search("weekends", {"max_search_results": 1, "about": "vol_devon"})
    assert len(scoped) == 1 and scoped[0].metadata["about_id"] == "vol_devon"
    assert await memory.search("weekends", {"about": "vol_maria"}) == []


# --- search behaviour -----------------------------------------------------------------


def test_bm25_ranks_the_most_relevant_note_first(memory):
    hits = memory.search_sync("dialysis ride for Mr. Okafor")
    assert hits[0].content.startswith("Mr. Okafor")


def test_search_scopes_to_one_person(memory):
    hits = memory.search_sync("truck", about="vol_devon")
    assert len(hits) == 1 and "pickup truck" in hits[0].content


def test_search_respects_the_limit(memory):
    assert len(memory.search_sync("the", limit=2)) <= 2


@pytest.mark.parametrize("query", ['dialysis "ride', "OR AND NOT(", "***", "", "   "])
def test_punctuation_and_operators_cannot_break_the_query(memory, query):
    assert isinstance(memory.search_sync(query), list)


def test_metadata_carries_about_id_kind_and_timestamp(memory, clock):
    hits = memory.search_sync("dialysis")
    metadata = hits[0].metadata
    assert metadata["about_id"] == "vol_maria"
    assert metadata["kind"] == "preference"
    assert metadata["ts"] == clock.now().isoformat()
    assert metadata["id"].startswith("mem_")


def test_unknown_terms_return_nothing(memory):
    assert memory.search_sync("submarine repair") == []


def test_recent_returns_newest_first(memory, clock):
    clock.advance(hours=1)
    memory.add_sync("Newest note about the bake sale.", {"about_id": "rqr_bell"})
    recent = memory.recent(limit=2)
    assert recent[0].content.startswith("Newest note")


def test_writing_the_same_id_twice_replaces_rather_than_duplicates(memory):
    memory.add_sync("First version.", {"id": "mem_fixed"})
    memory.add_sync("Second version.", {"id": "mem_fixed"})
    hits = memory.search_sync("version")
    assert [h.content for h in hits] == ["Second version."]


def test_empty_content_is_rejected(memory):
    with pytest.raises(ValueError):
        memory.add_sync("   ")


def test_reset_and_count(memory):
    assert memory.count() == len(NOTES)
    memory.reset()
    assert memory.count() == 0
    assert memory.search_sync("dialysis") == []


def test_add_messages_stores_the_conversation_text(memory):
    ids = memory.add_messages_sync(
        [
            {"role": "user", "content": [{"text": "Can someone drive Ezra Thursday?"}]},
            {"role": "assistant", "content": [{"toolUse": {"name": "x", "input": {}}}]},
            {"role": "assistant", "content": [{"text": "Maria confirmed."}]},
        ]
    )
    assert len(ids) == 2
    hits = memory.search_sync("Maria confirmed")
    assert hits[0].metadata["kind"] == "message"
    assert hits[0].metadata["role"] == "assistant"


def test_notes_persist_in_a_file_across_connections(tmp_path, clock):
    path = str(tmp_path / "memory.db")
    first = SqliteMemoryStore(path, clock=clock)
    first.add_sync("Rosa loves visiting Mrs. Chen on Fridays.", {"about_id": "vol_rosa"})
    first.close()
    second = SqliteMemoryStore(path, clock=clock)
    assert second.search_sync("Fridays")[0].content.startswith("Rosa")
    second.close()


# --- helpers --------------------------------------------------------------------------


def test_search_memory_and_add_memory_use_the_sync_path(memory):
    assert add_memory(memory, "Kwame is not police-checked yet.", {"about_id": "vol_kwame"}) is True
    hits = search_memory(memory, "police-checked", about="vol_kwame")
    assert hits[0]["content"].startswith("Kwame")
    assert hits[0]["metadata"]["about_id"] == "vol_kwame"


def test_helpers_are_no_ops_without_a_store():
    assert search_memory(None, "anything") == []
    assert add_memory(None, "anything") is False


class AsyncOnlyStore:
    """A third-party store with only the async protocol methods."""

    name = "async_only"
    description = "async only"
    max_search_results = 3
    writable = True
    extraction = False

    def __init__(self) -> None:
        self.added: list[str] = []

    async def search(self, query, options=None):
        return [MemoryEntry(content=f"about {query}", metadata={"opts": dict(options or {})})]

    async def add(self, content, metadata=None):
        self.added.append(content)
        return "ok"


def test_helpers_fall_back_to_the_async_protocol():
    store = AsyncOnlyStore()
    hits = search_memory(store, "rides", limit=2, about="vol_maria")
    assert hits[0]["content"] == "about rides"
    assert hits[0]["metadata"]["opts"] == {"max_search_results": 2, "about": "vol_maria"}
    assert add_memory(store, "a note") is True
    assert store.added == ["a note"]


class BrokenStore:
    name = "broken"
    description = None
    max_search_results = 1
    writable = True
    extraction = False

    async def search(self, query, options=None):
        raise RuntimeError("backend down")

    async def add(self, content, metadata=None):
        raise RuntimeError("backend down")


def test_a_failing_backend_degrades_instead_of_raising():
    assert search_memory(BrokenStore(), "anything") == []
    assert add_memory(BrokenStore(), "anything") is False


async def test_run_sync_works_inside_a_running_event_loop():
    async def answer() -> int:
        await asyncio.sleep(0)
        return 41 + 1

    assert run_sync(answer()) == 42


def test_entry_to_dict_normalizes_every_shape():
    assert entry_to_dict({"content": "x", "metadata": {"a": 1}}) == {"content": "x", "metadata": {"a": 1}}
    entry = MemoryEntry(content="y", store_name="s", metadata={"b": 2})
    assert entry_to_dict(entry) == {"content": "y", "metadata": {"b": 2, "store": "s"}}
    assert entry_to_dict("plain") == {"content": "plain", "metadata": {}}


# --- factory --------------------------------------------------------------------------


def test_make_memory_store_picks_sqlite_in_demo_mode():
    store = make_memory_store(Settings(mode="demo", sqlite_path=":memory:", memory_id="mem-123"))
    assert isinstance(store, SqliteMemoryStore)
    store.close()


def test_make_memory_store_picks_agentcore_when_live_with_a_memory_id():
    store = make_memory_store(
        Settings(mode="live", sqlite_path=":memory:", memory_id="mem-123", aws_region="us-east-1")
    )
    assert isinstance(store, AgentCoreMemoryStore)
    assert store.memory_id == "mem-123"


def test_live_without_a_memory_id_still_gets_local_memory():
    store = make_memory_store(Settings(mode="live", sqlite_path=":memory:"))
    assert isinstance(store, SqliteMemoryStore)
    store.close()


# --- AgentCore store ------------------------------------------------------------------


class FakeMemoryClient:
    """Stands in for ``bedrock_agentcore.memory.MemoryClient``."""

    def __init__(self, records=None, fail=False) -> None:
        self.records = records or []
        self.fail = fail
        self.retrieved: list[dict] = []
        self.events: list[dict] = []

    def retrieve_memories(self, **kwargs):
        if self.fail:
            raise RuntimeError("no credentials")
        self.retrieved.append(kwargs)
        return self.records

    def create_event(self, **kwargs):
        self.events.append(kwargs)
        return {"event": {"eventId": "evt-1"}}


def test_agentcore_store_never_builds_a_client_until_used():
    store = AgentCoreMemoryStore("mem-123", "us-east-1")
    assert store._client is None
    assert store.namespace_for("vol_maria") == "/porchlight/vol_maria/"
    assert store.namespace_for(None) == "/porchlight/group/"


def test_agentcore_search_maps_records_to_entries():
    client = FakeMemoryClient(
        records=[
            {
                "memoryRecordId": "rec-1",
                "content": {"text": "Maria prefers mornings."},
                "namespaces": ["/porchlight/vol_maria/"],
                "createdAt": "2026-09-01T10:00:00Z",
                "score": 0.87,
            },
            {"memoryRecordId": "rec-2", "content": {"text": ""}},
        ]
    )
    store = AgentCoreMemoryStore("mem-123", client=client)
    hits = store.search_sync("mornings", limit=4, about="vol_maria")
    assert len(hits) == 1
    assert hits[0].content == "Maria prefers mornings."
    assert hits[0].metadata["score"] == 0.87
    assert client.retrieved[0]["namespace"] == "/porchlight/vol_maria/"
    assert client.retrieved[0]["top_k"] == 4


def test_agentcore_search_without_about_uses_the_namespace_path():
    client = FakeMemoryClient()
    AgentCoreMemoryStore("mem-123", client=client).search_sync("anything")
    assert client.retrieved[0]["namespace_path"] == "/porchlight/"


def test_agentcore_search_failure_returns_nothing():
    store = AgentCoreMemoryStore("mem-123", client=FakeMemoryClient(fail=True))
    assert store.search_sync("anything") == []


def test_agentcore_add_writes_an_event():
    client = FakeMemoryClient()
    store = AgentCoreMemoryStore("mem-123", client=client)
    assert store.add_sync("Devon only does weekends.", {"about_id": "vol_devon"}) == "evt-1"
    event = client.events[0]
    assert event["actor_id"] == "vol_devon"
    assert event["messages"] == [("Devon only does weekends.", "ASSISTANT")]
    assert event["metadata"]["about_id"] == {"stringValue": "vol_devon"}


# --- MemoryManager wiring -------------------------------------------------------------


def test_make_memory_manager_returns_none_without_memory(store, clock):
    assert make_memory_manager(make_ctx(store, clock, with_memory=False)) is None


def test_make_memory_manager_wraps_the_context_store(store, clock):
    ctx = make_ctx(store, clock)
    manager = make_memory_manager(ctx)
    assert isinstance(manager, MemoryManager)


def test_an_agent_gains_the_search_memory_tool(store, clock):
    ctx = make_ctx(store, clock)
    ctx.memory.add_sync("Maria prefers mornings.", {"about_id": "vol_maria"})
    agent = Agent(
        model=MockModel(default_structured=False),
        memory_manager=make_memory_manager(ctx),
        callback_handler=None,
        name="matcher",
    )
    assert "search_memory" in agent.tool_names
