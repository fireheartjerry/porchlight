"""Email delivery through Amazon SES.

Boto3 is imported lazily and only when ``dry_run`` is off, so this module is importable — and
usable in the demo — with no AWS credentials at all.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..clock import Clock, SystemClock
from ..models import InboundReply, MessageStatus, OutboundMessage, Recipient
from ..store.base import Store

logger = logging.getLogger(__name__)

DEFAULT_FROM_ADDR = "porchlight@example.org"
DEFAULT_SUBJECT = "A neighbour could use a hand"


class EmailChannel:
    """Send outbound messages as email via SES.

    Args:
        ses_client_factory: Returns a boto3 SES client; defaults to a lazily created one.
        from_addr: Verified sender address; defaults to ``$PORCHLIGHT_FROM_ADDR``.
        dry_run: When True (the default) nothing is sent — the message is logged and marked sent,
            which is what local runs and CI want.
        store: Where messages are persisted, and where recipient addresses are looked up.
        clock: Time source.
        region: AWS region for the default client factory.
        group_name: Used in the subject line.
    """

    def __init__(
        self,
        ses_client_factory: Callable[[], Any] | None = None,
        from_addr: str | None = None,
        dry_run: bool = True,
        *,
        store: Store | None = None,
        clock: Clock | None = None,
        region: str | None = None,
        group_name: str = "Porchlight",
    ) -> None:
        self.from_addr = from_addr or os.environ.get("PORCHLIGHT_FROM_ADDR", DEFAULT_FROM_ADDR)
        self.dry_run = dry_run
        self.store = store
        self.clock = clock or SystemClock()
        self.region = region
        self.group_name = group_name
        self._factory = ses_client_factory
        self._client: Any | None = None
        self.sent: list[OutboundMessage] = []

    def __repr__(self) -> str:
        return f"EmailChannel(from={self.from_addr!r}, dry_run={self.dry_run})"

    @property
    def client(self) -> Any:
        """The SES client, built on first real send."""
        if self._client is None:
            if self._factory is not None:
                self._client = self._factory()
            else:
                import boto3

                self._client = boto3.client("ses", region_name=self.region)
        return self._client

    # --- Channel ------------------------------------------------------------

    def send(self, msg: OutboundMessage) -> OutboundMessage:
        """Send ``msg`` by email (or log it when ``dry_run``)."""
        msg.channel = "email"
        address = self.address_for(msg)
        if self.dry_run or address is None:
            if address is None:
                logger.warning("no email address for %s %s; logging instead", msg.to, msg.recipient_id)
            else:
                logger.info("[dry-run] email to %s: %s", address, msg.body)
            msg.sent_at = self.clock.now()
            msg.status = MessageStatus.SENT
        else:
            try:
                self.client.send_email(
                    Source=self.from_addr,
                    Destination={"ToAddresses": [address]},
                    Message={
                        "Subject": {"Data": self.subject_for(msg)},
                        "Body": {"Text": {"Data": msg.body}},
                    },
                )
                msg.sent_at = self.clock.now()
                msg.status = MessageStatus.SENT
            except Exception:
                logger.exception("SES send failed for message %s", msg.id)
                msg.status = MessageStatus.FAILED
        if self.store is not None:
            self.store.put_message(msg)
        self.sent.append(msg)
        return msg

    def schedule(self, msg: OutboundMessage, when: datetime) -> OutboundMessage:
        """Queue ``msg`` for ``when``; the hourly sweep sends it."""
        msg.channel = "email"
        msg.scheduled_for = when
        msg.status = MessageStatus.SCHEDULED
        if self.store is not None:
            self.store.put_message(msg)
        return msg

    def fetch_replies(self, request_id: str) -> list[InboundReply]:
        """Email replies arrive out of band (SES receipt rule to the API), so never here."""
        return []

    # --- helpers ------------------------------------------------------------

    def address_for(self, msg: OutboundMessage) -> str | None:
        """Resolve the recipient's email address from the store."""
        if self.store is None or not msg.recipient_id:
            return None
        if msg.to == Recipient.VOLUNTEER:
            volunteer = self.store.get_volunteer(msg.recipient_id)
            return volunteer.email if volunteer else None
        if msg.to == Recipient.REQUESTER:
            requester = self.store.get_requester(msg.recipient_id)
            contact = requester.contact if requester else None
            return contact if contact and "@" in contact else None
        return None

    def subject_for(self, msg: OutboundMessage) -> str:
        """Subject line for one message."""
        summary = ""
        if self.store is not None and msg.request_id:
            request = self.store.get_request(msg.request_id)
            summary = request.summary if request else ""
        return f"[{self.group_name}] {summary or DEFAULT_SUBJECT}"
