"""Record an inbound message as an :class:`~porchlight.models.AidRequest`.

This is the deterministic half of intake: find (or create) the requester, write a ``new``
request with the raw text, and log that it arrived. All of the interpretation — category,
urgency, window, safety and money flags — happens later in the intake *agent* node, which
reads ``raw_text`` off the row this module wrote.
"""

from __future__ import annotations

import logging

from .context import AppContext
from .models import AidRequest, LogEvent, LogKind, Requester, RequestStatus, Source

logger = logging.getLogger(__name__)

PHOTO_MARKER = "[photo of a paper slip attached]"
"""Placed in ``raw_text`` when a request arrives as an image with no typed text."""

IMAGE_LOG_SUMMARY = "Inbound photo attached"
"""Summary of the log event that carries an inbound image for the intake agent."""


def _display_name(contact: str | None) -> str:
    """Guess a human-readable name from a contact string.

    Emails become their local part ("petra.novak@x.org" → "Petra Novak"); anything else falls
    back to a neutral placeholder the intake agent can overwrite once it has read the text.
    """
    if not contact:
        return "Unknown neighbour"
    if "@" in contact:
        local = contact.split("@", 1)[0]
        parts = [p for p in local.replace("_", ".").replace("-", ".").split(".") if p]
        if parts:
            return " ".join(part.capitalize() for part in parts)
    return contact


def _find_or_create_requester(ctx: AppContext, contact: str | None) -> Requester | None:
    """Return the requester this message came from, creating one when the contact is new."""
    if not contact or not contact.strip():
        return None
    contact = contact.strip()
    existing = ctx.store.find_requester_by_contact(contact)
    if existing is not None:
        return existing
    created = Requester(name=_display_name(contact), contact=contact, first_seen=ctx.now())
    ctx.store.put_requester(created)
    logger.info("new requester %s from %s", created.id, contact)
    return created


def create_request_from_inbox(
    ctx: AppContext,
    text: str,
    source: Source | str,
    contact: str | None = None,
    image_base64: str | None = None,
) -> AidRequest:
    """Turn one inbound message into a stored :class:`AidRequest`.

    Args:
        ctx: Application context (store, clock, trace sink).
        text: The raw message exactly as it arrived. May be empty when only a photo was sent.
        source: Where it came from — ``form``, ``email``, ``sms``, ``voicemail``, ``paper``, ``api``.
        contact: Phone, email, or handle. Matched against known requesters; a new one is created
            when it is unknown. ``None`` leaves the request unattributed for the agent to resolve.
        image_base64: Base64 photo of a paper slip. Stored on a log event (not on the request
            row) so the intake agent can read it without bloating every request payload.

    Returns:
        The persisted request, status ``new``.

    Raises:
        ValueError: When neither text nor an image was supplied.
    """
    body = (text or "").strip()
    if not body and not image_base64:
        raise ValueError("an inbound message needs text or an image")
    if not body:
        body = PHOTO_MARKER

    requester = _find_or_create_requester(ctx, contact)
    now = ctx.now()
    request = AidRequest(
        source=Source(source),
        raw_text=body,
        requester_id=requester.id if requester else None,
        status=RequestStatus.NEW,
        first_time_requester=requester.history_count == 0 if requester else True,
        created_at=now,
        updated_at=now,
    )
    ctx.store.put_request(request)

    if requester is not None:
        requester.history_count += 1
        ctx.store.put_requester(requester)

    who = requester.name if requester else "an unknown contact"
    summary = f"Inbound {request.source.value} from {who}"
    ctx.store.append_log(
        LogEvent(
            ts=now,
            request_id=request.id,
            agent="intake",
            kind=LogKind.TOOL_CALL,
            summary=summary,
            # The intake agent's own row ("Read Ezra's text: …") tells the coordinator this
            # better a beat later, so the arrival itself is bookkeeping.
            visible=False,
            detail={
                "source": request.source.value,
                "contact": contact,
                "requester_id": request.requester_id,
                "first_time_requester": request.first_time_requester,
                "chars": len(body),
                "has_image": bool(image_base64),
            },
            autonomous=True,
        )
    )
    if image_base64:
        ctx.store.append_log(
            LogEvent(
                ts=now,
                request_id=request.id,
                agent="intake",
                kind=LogKind.TOOL_CALL,
                summary=IMAGE_LOG_SUMMARY,
                detail={"image_base64": image_base64},
                autonomous=True,
            )
        )

    ctx.emit(
        {
            "type": "log",
            "ts": now.isoformat(),
            "request_id": request.id,
            "agent": "intake",
            "summary": summary,
            "detail": {"kind": LogKind.TOOL_CALL.value, "source": request.source.value},
        }
    )
    return request


def inbound_image(ctx: AppContext, request_id: str) -> str | None:
    """Return the base64 image recorded with ``request_id``, if any.

    The intake agent node uses this to feed a photographed paper slip to the model.
    """
    for event in ctx.store.list_log(request_id=request_id, limit=50):
        if event.summary == IMAGE_LOG_SUMMARY:
            image = event.detail.get("image_base64")
            if isinstance(image, str):
                return image
    return None


__all__ = ["PHOTO_MARKER", "create_request_from_inbox", "inbound_image"]
