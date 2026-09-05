"""Messaging tools: the only way Porchlight talks to a human.

Everything here goes through ``ctx.channel`` (simulated locally, SES in production) and leaves a
quiet-log line in plain English, because "what did it send on my behalf?" is the first question
a coordinator asks.
"""

from __future__ import annotations

from typing import Any

from strands import tool
from strands.types.tools import ToolContext

from ..context import AppContext, get_ctx
from ..models import LogKind, MessageStatus, OutboundMessage, Recipient, jsonable
from ._common import agent_name, error, parse_iso, record, trace
from .summaries import describe_tool


def _recipient_name(ctx: AppContext, to: Recipient, recipient_id: str) -> str:
    """Human name for the recipient, falling back to the id."""
    if to == Recipient.VOLUNTEER:
        volunteer = ctx.store.get_volunteer(recipient_id)
        return volunteer.name if volunteer else recipient_id
    if to == Recipient.REQUESTER:
        requester = ctx.store.get_requester(recipient_id)
        return requester.name if requester else recipient_id
    return "the coordinator"


def _new_message(
    ctx: AppContext, request_id: str, to: Recipient, recipient_id: str, body: str
) -> OutboundMessage:
    """Build a draft message for this deployment's channel."""
    return OutboundMessage(
        request_id=request_id,
        to=to,
        recipient_id=recipient_id,
        body=body,
        channel="sim" if ctx.settings.is_demo else "email",
        status=MessageStatus.DRAFT,
        created_at=ctx.clock.now(),
    )


def _as_recipient(to: str) -> Recipient | None:
    try:
        return Recipient(to)
    except ValueError:
        return None


def send_message_impl(
    ctx: AppContext,
    request_id: str,
    to: str,
    recipient_id: str,
    body: str,
    *,
    agent: str | None = None,
) -> dict[str, Any]:
    """Send a message now (the plain-function form)."""
    recipient = _as_recipient(to)
    if recipient is None:
        return error(f"invalid recipient kind {to!r}; use volunteer, requester, or coordinator")
    if not body.strip():
        return error("refusing to send an empty message")
    message = _new_message(ctx, request_id, recipient, recipient_id, body)
    sent = ctx.channel.send(message)
    ctx.store.put_message(sent)
    args = {"request_id": request_id, "to": to, "recipient_id": recipient_id, "body": body}
    note = describe_tool(ctx, "send_message", args)
    record(
        ctx,
        LogKind.MESSAGE_SENT,
        note.summary,
        request_id=request_id,
        agent=agent,
        visible=note.visible,
        detail={
            "message_id": sent.id,
            "to": str(recipient),
            "recipient_id": recipient_id,
            "recipient_name": _recipient_name(ctx, recipient, recipient_id),
            "body": body,
        },
    )
    return {"message_id": sent.id, "status": str(sent.status)}


def schedule_message_impl(
    ctx: AppContext,
    request_id: str,
    to: str,
    recipient_id: str,
    body: str,
    send_at_iso: str,
    *,
    agent: str | None = None,
) -> dict[str, Any]:
    """Queue a message for later (the plain-function form)."""
    recipient = _as_recipient(to)
    if recipient is None:
        return error(f"invalid recipient kind {to!r}; use volunteer, requester, or coordinator")
    when = parse_iso(send_at_iso)
    if when is None:
        return error(f"invalid send_at_iso {send_at_iso!r}; use an ISO-8601 timestamp")
    if not body.strip():
        return error("refusing to schedule an empty message")
    message = _new_message(ctx, request_id, recipient, recipient_id, body)
    scheduled = ctx.channel.schedule(message, when)
    ctx.store.put_message(scheduled)
    args = {
        "request_id": request_id,
        "to": to,
        "recipient_id": recipient_id,
        "body": body,
        "send_at_iso": when.isoformat(),
    }
    note = describe_tool(ctx, "schedule_message", args)
    record(
        ctx,
        LogKind.MESSAGE_SENT,
        note.summary,
        request_id=request_id,
        agent=agent,
        visible=note.visible,
        detail={
            "message_id": scheduled.id,
            "to": str(recipient),
            "recipient_id": recipient_id,
            "recipient_name": _recipient_name(ctx, recipient, recipient_id),
            "send_at": when.isoformat(),
            "body": body,
        },
    )
    return {
        "message_id": scheduled.id,
        "status": str(scheduled.status),
        "scheduled_for": when.isoformat(),
    }


def read_replies_impl(ctx: AppContext, request_id: str, *, agent: str | None = None) -> list[dict[str, Any]]:
    """Read the replies that have arrived for a request (the plain-function form)."""
    replies = ctx.channel.fetch_replies(request_id)
    payload = [reply if isinstance(reply, dict) else jsonable(reply) for reply in replies]
    trace(
        ctx,
        "tool_call",
        describe_tool(ctx, "read_replies", {"request_id": request_id}, payload).summary,
        request_id=request_id,
        agent=agent,
        detail={"count": len(payload), "replies": payload},
    )
    return payload


@tool(context=True)
def send_message(request_id: str, to: str, recipient_id: str, body: str, tool_context: ToolContext) -> dict:
    """Send a message on the group's behalf, right now.

    Write like a neighbour, not a dispatcher: use the person's name, say what is needed and when,
    say who it is for, and make it easy to say no. Two or three sentences.

    Args:
        request_id: The aid request this message is about.
        to: ``"volunteer"``, ``"requester"``, or ``"coordinator"``.
        recipient_id: Id of the volunteer or requester being messaged.
        body: The message text.

    Returns:
        ``{"message_id": str, "status": str}``.
    """
    ctx = get_ctx(tool_context)
    return send_message_impl(
        ctx,
        request_id,
        to,
        recipient_id,
        body,
        agent=agent_name(tool_context.invocation_state.get("agent")),
    )


@tool(context=True)
def schedule_message(
    request_id: str,
    to: str,
    recipient_id: str,
    body: str,
    send_at_iso: str,
    tool_context: ToolContext,
) -> dict:
    """Queue a message to go out later: reminders, morning sends after quiet hours, check-ins.

    Args:
        request_id: The aid request this message is about.
        to: ``"volunteer"``, ``"requester"``, or ``"coordinator"``.
        recipient_id: Id of the volunteer or requester being messaged.
        body: The message text.
        send_at_iso: When to send it, as an ISO-8601 timestamp.

    Returns:
        ``{"message_id": str, "status": str, "scheduled_for": iso}``.
    """
    ctx = get_ctx(tool_context)
    return schedule_message_impl(
        ctx,
        request_id,
        to,
        recipient_id,
        body,
        send_at_iso,
        agent=agent_name(tool_context.invocation_state.get("agent")),
    )


@tool(context=True)
def read_replies(request_id: str, tool_context: ToolContext) -> list[dict]:
    """Read volunteer replies that have arrived for a request.

    Args:
        request_id: The aid request to check.

    Returns:
        A list of ``{id, request_id, from_volunteer_id, text, received_at}`` dicts, oldest first.
    """
    ctx = get_ctx(tool_context)
    return read_replies_impl(ctx, request_id, agent=agent_name(tool_context.invocation_state.get("agent")))
