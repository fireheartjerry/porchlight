"""Outbound/inbound messaging. ``make_channel(settings, store, clock)`` picks one."""

from __future__ import annotations

from ..clock import Clock
from ..config import Settings
from ..models import InboundReply, OutboundMessage
from ..store.base import Store
from .base import Channel
from .email import EmailChannel
from .sim import ReplyFn, SimChannel

__all__ = [
    "Channel",
    "EmailChannel",
    "InboundReply",
    "OutboundMessage",
    "ReplyFn",
    "SimChannel",
    "make_channel",
]


def make_channel(
    settings: Settings,
    store: Store,
    clock: Clock | None = None,
    *,
    reply_fn: ReplyFn | None = None,
) -> Channel:
    """Return the channel configured by ``settings.mode``.

    Args:
        settings: Application settings; ``demo`` mode simulates, ``live`` mode sends email.
        store: Store the channel persists messages to.
        clock: Time source.
        reply_fn: Volunteer simulator for demo mode.

    Returns:
        A :class:`~porchlight.channels.sim.SimChannel` or
        :class:`~porchlight.channels.email.EmailChannel`. Neither touches AWS at import time.
    """
    if settings.is_demo:
        return SimChannel(store, clock, reply_fn)
    return EmailChannel(
        dry_run=False,
        store=store,
        clock=clock,
        region=settings.aws_region,
        group_name=settings.group_name,
    )
