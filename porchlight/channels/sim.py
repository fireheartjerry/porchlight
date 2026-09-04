"""The simulated channel used by the demo and every test.

Nothing leaves the machine. When Porchlight messages a volunteer, :class:`SimChannel` answers as
that volunteer would: either through the volunteer-simulator agent (``reply_fn``) or, with no
model available, through the scripted lines in :mod:`porchlight.sim.fixtures`. Replies are kept
in memory *and* mirrored into the quiet log, so a second process (the API, a later sweep) can
still read them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from ..clock import Clock, SystemClock
from ..models import (
    AidRequest,
    InboundReply,
    LogEvent,
    LogKind,
    MessageStatus,
    OutboundMessage,
    Recipient,
    Volunteer,
    jsonable,
)
from ..sim.fixtures import reply_for
from ..store.base import Store

logger = logging.getLogger(__name__)

ReplyFn = Callable[[Volunteer, AidRequest, str], str]

REPLY_LOG_KEY = "inbound_reply"
"""Key under ``LogEvent.detail`` that carries a serialized :class:`InboundReply`."""


class SimChannel:
    """A channel that stores messages and answers on the volunteer's behalf.

    Args:
        store: Where messages and the reply mirror are persisted.
        clock: Time source.
        reply_fn: Optional volunteer simulator, ``(volunteer, request, message_text) -> str``.
            When omitted (or when it raises), scripted fixture replies are used, which makes the
            whole demo deterministic.
        auto_reply: Set False to stop the channel answering, e.g. to test timeouts.
    """

    def __init__(
        self,
        store: Store,
        clock: Clock | None = None,
        reply_fn: ReplyFn | None = None,
        *,
        auto_reply: bool = True,
    ) -> None:
        self.store = store
        self.clock = clock or SystemClock()
        self.reply_fn = reply_fn
        self.auto_reply = auto_reply
        self.sent: list[OutboundMessage] = []
        self.scheduled: list[OutboundMessage] = []
        self._replies: dict[str, list[InboundReply]] = {}
        self._reply_index: dict[str, int] = {}

    def __repr__(self) -> str:
        return f"SimChannel(sent={len(self.sent)}, scheduled={len(self.scheduled)})"

    # --- outbound -----------------------------------------------------------

    def send(self, msg: OutboundMessage) -> OutboundMessage:
        """Mark ``msg`` sent, persist it, and (for volunteers) produce a reply."""
        now = self.clock.now()
        msg.channel = "sim"
        msg.sent_at = now
        msg.status = MessageStatus.SENT
        index = self._take_index(msg)
        self.store.put_message(msg)
        self.sent.append(msg)
        if self.auto_reply and msg.to == Recipient.VOLUNTEER and msg.recipient_id:
            self._simulate_reply(msg, index)
        return msg

    def schedule(self, msg: OutboundMessage, when: datetime) -> OutboundMessage:
        """Queue ``msg`` for ``when``; nothing is simulated until it is actually sent."""
        msg.channel = "sim"
        msg.scheduled_for = when
        msg.status = MessageStatus.SCHEDULED
        self.store.put_message(msg)
        self.scheduled.append(msg)
        return msg

    # --- inbound ------------------------------------------------------------

    def fetch_replies(self, request_id: str) -> list[InboundReply]:
        """Replies for one request, oldest first, merged from memory and the quiet log."""
        seen: dict[str, InboundReply] = {r.id: r for r in self._replies.get(request_id, [])}
        for event in self.store.list_log(request_id=request_id, limit=200):
            payload = event.detail.get(REPLY_LOG_KEY)
            if isinstance(payload, dict) and payload.get("id") not in seen:
                try:
                    reply = InboundReply.model_validate(payload)
                except ValueError:  # pragma: no cover - defensive
                    continue
                seen[reply.id] = reply
        return sorted(seen.values(), key=lambda r: r.received_at)

    def inject_reply(self, request_id: str, volunteer_id: str, text: str) -> InboundReply:
        """Record a reply that came from somewhere else (the demo UI, a test, a real inbox)."""
        reply = InboundReply(
            request_id=request_id,
            from_volunteer_id=volunteer_id,
            text=text,
            received_at=self.clock.now(),
        )
        self._replies.setdefault(request_id, []).append(reply)
        volunteer = self.store.get_volunteer(volunteer_id)
        who = volunteer.name if volunteer else volunteer_id
        self.store.append_log(
            LogEvent(
                ts=reply.received_at,
                request_id=request_id,
                agent="channel",
                kind=LogKind.MESSAGE_SENT,
                summary=f"{who} replied: {text[:120]}",
                detail={REPLY_LOG_KEY: jsonable(reply)},
            )
        )
        return reply

    def set_reply_fn(self, reply_fn: ReplyFn | None) -> None:
        """Swap the volunteer simulator in (or out) after construction."""
        self.reply_fn = reply_fn

    # --- internals ----------------------------------------------------------

    def _take_index(self, msg: OutboundMessage) -> int:
        """Which scripted line this volunteer is up to; stable across a process."""
        volunteer_id = msg.recipient_id or ""
        if volunteer_id not in self._reply_index:
            prior = sum(
                1
                for stored in self.store.list_messages()
                if stored.recipient_id == volunteer_id
                and stored.to == Recipient.VOLUNTEER
                and stored.sent_at is not None
            )
            self._reply_index[volunteer_id] = prior
        index = self._reply_index[volunteer_id]
        self._reply_index[volunteer_id] = index + 1
        return index

    def _simulate_reply(self, msg: OutboundMessage, index: int) -> InboundReply | None:
        """Answer as the volunteer we just messaged."""
        volunteer = self.store.get_volunteer(msg.recipient_id or "")
        if volunteer is None:
            logger.debug("no volunteer %s to simulate a reply from", msg.recipient_id)
            return None
        request = self.store.get_request(msg.request_id) if msg.request_id else None
        text = reply_for(volunteer.id, index)
        if self.reply_fn is not None and request is not None:
            try:
                generated = self.reply_fn(volunteer, request, msg.body)
                if generated and generated.strip():
                    text = generated.strip()
            except Exception:  # pragma: no cover - a flaky simulator must not break the run
                logger.warning("volunteer simulator failed; using scripted reply", exc_info=True)
        return self.inject_reply(msg.request_id or "", volunteer.id, text)
