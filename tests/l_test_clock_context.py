"""The clock is injected context, not a tool (``docs/LIVE-FIXES.md`` E).

``strands_tools.current_time`` now logs "current_time is deprecated … Migration path: inject the
current time as context with ContextInjector" on every intake run. Porchlight carries the
Strands ``ContextInjector`` plugin instead: each agent gets a ``<current-time>`` block folded
into the model input before every call, which costs no round trip, never goes stale on a resumed
run, and never lands in durable history.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from strands.vended_plugins.context_injector import ContextInjector

import porchlight
from porchlight.agents import (
    build_intake_task,
    make_brief_agent,
    make_intake_agent,
    make_matcher_agent,
    make_outreach_agent,
    make_steward_agent,
)
from porchlight.agents.base import CLOCK_INJECTOR_NAME, clock_injector, render_now
from porchlight.agents.outputs import IntakeResult
from porchlight.clock import FrozenClock
from porchlight.config import Settings
from porchlight.context import AppContext, NullChannel
from porchlight.models import AidRequest, Source
from porchlight.sim.fixtures import seed_store
from porchlight.store.sqlite_store import SqliteStore
from porchlight.testing.mock_model import MockModel, MockTurn

DAYTIME = datetime(2026, 9, 8, 14, 0, 0, tzinfo=UTC)
"""Tuesday 10:00 in America/Toronto."""

NIGHT = datetime(2026, 9, 9, 2, 30, 0, tzinfo=UTC)
"""Tuesday 22:30 in America/Toronto — inside quiet hours."""

FACTORIES = (make_intake_agent, make_matcher_agent, make_outreach_agent, make_steward_agent, make_brief_agent)


def _context(now: datetime) -> AppContext:
    clock = FrozenClock(now)
    store = SqliteStore(":memory:")
    seed_store(store, clock)
    return AppContext(
        settings=Settings(mode="demo", model_provider="mock", store="sqlite", sqlite_path=":memory:"),
        store=store,
        channel=NullChannel(),
        memory=None,
        clock=clock,
        emit=lambda event: None,
    )


@pytest.fixture
def cctx() -> Iterator[AppContext]:
    ctx = _context(DAYTIME)
    yield ctx
    ctx.store.close()


# --------------------------------------------------------------------------------------
# What gets injected
# --------------------------------------------------------------------------------------


def test_the_block_carries_the_app_clock_and_the_group_timezone(cctx: AppContext) -> None:
    block = render_now(cctx)
    assert block.startswith("<current-time>") and block.endswith("</current-time>")
    assert "now_utc: 2026-09-08T14:00:00+00:00" in block
    assert "now_local: Tuesday 08 September 2026, 10:00 (America/Toronto)" in block
    assert "quiet_hours: no" in block


def test_the_block_says_when_it_is_quiet_hours() -> None:
    ctx = _context(NIGHT)
    try:
        block = render_now(ctx)
        assert "now_local: Tuesday 08 September 2026, 22:30" in block
        assert "quiet_hours: yes" in block
    finally:
        ctx.store.close()


def test_the_block_follows_the_clock_rather_than_being_captured_once(cctx: AppContext) -> None:
    """A card answered two hours later must not resume with the time it was filed at."""
    injector = clock_injector(cctx)
    first = render_now(cctx)
    cctx.clock.advance(hours=2)  # type: ignore[attr-defined]
    assert render_now(cctx) != first
    assert "16:00" in render_now(cctx)
    assert isinstance(injector, ContextInjector)


# --------------------------------------------------------------------------------------
# How it is attached
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("factory", FACTORIES, ids=lambda f: f.__name__)
def test_every_agent_carries_the_clock_injector(cctx: AppContext, factory) -> None:
    agent = factory(cctx)
    plugin = agent._plugin_registry._plugins[CLOCK_INJECTOR_NAME]  # type: ignore[attr-defined]
    assert isinstance(plugin, ContextInjector)


def test_intake_no_longer_carries_a_clock_tool(cctx: AppContext) -> None:
    assert make_intake_agent(cctx).tool_names == [
        "lookup_requester_history",
        "find_similar_open_requests",
    ]


IMPORTS_STRANDS_TOOLS = re.compile(r"^\s*(?:from|import)\s+strands_tools\b", re.MULTILINE)


def test_nothing_in_the_package_imports_the_deprecated_tool() -> None:
    """The deprecation warning is gone because the import is gone."""
    root = Path(porchlight.__file__).parent
    offenders = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if IMPORTS_STRANDS_TOOLS.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_intake_prompt_points_at_the_injected_block_not_a_tool(cctx: AppContext) -> None:
    from porchlight.agents.prompts import intake_prompt

    prompt = intake_prompt(cctx.settings)
    assert "`<current-time>`" in prompt
    assert "you do not need a clock tool" in prompt
    assert "Call `current_time`" not in prompt


# --------------------------------------------------------------------------------------
# End to end: the model sees it, the transcript does not
# --------------------------------------------------------------------------------------


def test_the_model_is_given_the_time_and_the_transcript_stays_clean(
    cctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = MockModel(
        script=[MockTurn(structured=IntakeResult(summary="Ride to dialysis Thursday 9am"))],
        output_models=[IntakeResult],
    )
    monkeypatch.setattr("porchlight.agents.base.make_model", lambda settings, tier: model)
    request = AidRequest(raw_text="could someone drive me thursday morning?", source=Source.SMS)
    cctx.store.put_request(request)

    agent = make_intake_agent(cctx)
    agent(build_intake_task(request), invocation_state={"ctx": cctx, "request_id": request.id})

    blocks = [
        block["text"]
        for call in model.calls
        for message in call["messages"]
        for block in message["content"]
        if isinstance(block, dict) and "text" in block
    ]
    assert any("<current-time>" in text for text in blocks), "the model never saw the time"
    assert any("now_local: Tuesday 08 September 2026, 10:00" in text for text in blocks)
    assert "<current-time>" not in str(agent.messages), "injection must stay out of durable history"
