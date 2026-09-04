"""Outbound/inbound messaging. ``make_channel(settings, store, clock)`` picks one."""

from __future__ import annotations

import logging

from ..clock import Clock
from ..config import Settings
from ..models import InboundReply, OutboundMessage
from ..store.base import Store
from .base import Channel
from .email import DEFAULT_FROM_ADDR, EmailChannel
from .sim import ReplyFn, SimChannel

logger = logging.getLogger(__name__)

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

    Live mode still refuses to send from the placeholder address: SES would reject every
    message from an unverified sender, and a deployment whose messages all silently fail is
    worse than one that logs them. Set ``PORCHLIGHT_FROM_ADDR`` to a verified sender to send
    for real.
    """
    if settings.is_demo:
        return SimChannel(store, clock, reply_fn)
    unverified = settings.from_addr.strip().lower() == DEFAULT_FROM_ADDR
    if unverified:
        logger.warning(
            "PORCHLIGHT_FROM_ADDR is still %r, so email is logged instead of sent. "
            "Set it to an SES-verified sender to send for real.",
            DEFAULT_FROM_ADDR,
        )
    return EmailChannel(
        from_addr=settings.from_addr,
        dry_run=unverified,
        store=store,
        clock=clock,
        region=settings.aws_region,
        group_name=settings.group_name,
    )
