"""The one object every tool, agent, and graph node receives: :class:`AppContext`."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .clock import Clock, SystemClock
from .config import Settings, get_settings
from .models import MessageStatus, OutboundMessage, utcnow
from .store import Store, make_store

if TYPE_CHECKING:  # pragma: no cover - typing only
    from strands.types.tools import ToolContext

logger = logging.getLogger(__name__)


def _noop_emit(event: dict) -> None:
    """Default trace sink: drop the event."""
    return None


class NullChannel:
    """In-memory stand-in for a real channel: records messages, never replies.

    Used until :class:`porchlight.channels.sim.SimChannel` exists, and in tests that only
    care that a message was produced.
    """

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []
        self.scheduled: list[OutboundMessage] = []

    def send(self, msg: OutboundMessage) -> OutboundMessage:
        """Mark ``msg`` sent and record it."""
        msg.sent_at = msg.sent_at or utcnow()
        msg.status = MessageStatus.SENT
        self.sent.append(msg)
        return msg

    def fetch_replies(self, request_id: str) -> list[Any]:
        """No channel, so never any replies."""
        return []

    def schedule(self, msg: OutboundMessage, when: datetime) -> OutboundMessage:
        """Mark ``msg`` scheduled for ``when`` and record it."""
        msg.scheduled_for = when
        msg.status = MessageStatus.SCHEDULED
        self.scheduled.append(msg)
        return msg

    def __repr__(self) -> str:
        return f"NullChannel(sent={len(self.sent)}, scheduled={len(self.scheduled)})"


@dataclass
class AppContext:
    """Everything a tool needs, handed through ``invocation_state["ctx"]``."""

    settings: Settings
    store: Store
    channel: Any
    memory: Any | None
    clock: Clock
    emit: Callable[[dict], None] = field(default=_noop_emit)

    def now(self) -> datetime:
        """Current time according to this context's clock."""
        return self.clock.now()


def get_ctx(tool_context: ToolContext) -> AppContext:
    """Pull the :class:`AppContext` out of a tool's invocation state.

    Args:
        tool_context: The ``ToolContext`` injected by ``@tool(context=True)``.

    Raises:
        RuntimeError: When the agent was invoked without ``invocation_state={"ctx": ...}``.
    """
    ctx = tool_context.invocation_state.get("ctx")
    if ctx is None:
        raise RuntimeError(
            "no AppContext in invocation_state; invoke the agent with invocation_state={'ctx': ctx}"
        )
    return ctx


def _build_channel(settings: Settings, store: Store, clock: Clock) -> Any:
    """Build the configured channel: ``SimChannel`` in demo mode, ``EmailChannel`` live.

    Both are constructed through :func:`porchlight.channels.make_channel` so the live channel
    gets the store it needs to resolve volunteer addresses. A failure to import the messaging
    stack degrades to :class:`NullChannel` rather than taking the process down.
    """
    try:
        from .channels import make_channel
    except ImportError:  # pragma: no cover - messaging stack always present in this repo
        logger.warning("channels package unavailable; using NullChannel")
        return NullChannel()
    return make_channel(settings, store, clock)


def _build_memory(settings: Settings) -> Any | None:
    """Build the long-term memory store: SQLite in demo mode, AgentCore Memory when configured."""
    try:
        from .memory import make_memory_store
    except ImportError:  # pragma: no cover - memory package always present in this repo
        logger.warning("memory package unavailable; running without long-term memory")
        return None
    return make_memory_store(settings)


def build_context(settings: Settings | None = None, **overrides: Any) -> AppContext:
    """Assemble an :class:`AppContext` from settings.

    Demo mode wires ``SqliteStore`` + :class:`~porchlight.channels.sim.SimChannel` +
    :class:`~porchlight.memory.sqlite_store.SqliteMemoryStore`; live mode wires the configured
    store, :class:`~porchlight.channels.email.EmailChannel`, and AgentCore Memory. The channel
    and memory packages are imported lazily so importing this module never pulls in boto3.

    Args:
        settings: Settings to use; defaults to :func:`porchlight.config.get_settings`.
        **overrides: Any :class:`AppContext` field to override (``store``, ``channel``,
            ``memory``, ``clock``, ``emit``).

    Returns:
        A ready-to-use context.
    """
    settings = settings or get_settings()
    clock: Clock = overrides.pop("clock", None) or SystemClock()
    store: Store = overrides.pop("store", None) or make_store(settings)
    channel = overrides.pop("channel", None)
    if channel is None:
        channel = _build_channel(settings, store, clock)
    memory = overrides.pop("memory", "__unset__")
    if memory == "__unset__":
        memory = _build_memory(settings)
    emit: Callable[[dict], None] = overrides.pop("emit", None) or _noop_emit
    if overrides:
        raise TypeError(f"unexpected overrides: {sorted(overrides)}")
    return AppContext(settings=settings, store=store, channel=channel, memory=memory, clock=clock, emit=emit)
