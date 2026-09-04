"""The channel contract: how Porchlight talks to volunteers and requesters."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from ..models import InboundReply, OutboundMessage

__all__ = ["Channel", "InboundReply", "OutboundMessage"]


@runtime_checkable
class Channel(Protocol):
    """Somewhere messages go out and replies come back.

    Implementations are responsible for persisting the messages they handle (via
    ``store.put_message``) so the quiet log and the API see the same history.
    """

    def send(self, msg: OutboundMessage) -> OutboundMessage:
        """Deliver ``msg`` now, setting ``sent_at`` and ``status``, and return it."""
        ...

    def fetch_replies(self, request_id: str) -> list[InboundReply]:
        """Return replies received for a request, oldest first."""
        ...

    def schedule(self, msg: OutboundMessage, when: datetime) -> OutboundMessage:
        """Queue ``msg`` for later delivery and return it."""
        ...
