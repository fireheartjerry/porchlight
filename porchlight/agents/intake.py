"""The intake agent: any inbound message (including a photo of a paper slip) → ``IntakeResult``."""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

from strands import Agent
from strands_tools import current_time

from ..context import AppContext
from ..models import AidRequest
from ..tools import find_similar_open_requests, lookup_requester_history
from .base import build_agent
from .outputs import IntakeResult
from .prompts import intake_prompt

logger = logging.getLogger(__name__)

_PNG_MAGIC = b"\x89PNG"
_GIF_MAGIC = b"GIF8"
_WEBP_MAGIC = b"WEBP"

__all__ = ["build_intake_task", "make_intake_agent"]


def make_intake_agent(ctx: AppContext) -> Agent:
    """Build the intake agent (fast tier, reads history, never contacts anybody)."""
    return build_agent(
        ctx,
        name="intake",
        system_prompt=intake_prompt(ctx.settings),
        tools=[current_time, lookup_requester_history, find_similar_open_requests],
        output_model=IntakeResult,
        tier="haiku",
        description="Turns an inbound message into a structured aid request.",
    )


def _image_format(raw: bytes) -> str:
    """Sniff the image format from its magic bytes; default to png."""
    if raw.startswith(_PNG_MAGIC):
        return "png"
    if raw.startswith(b"\xff\xd8"):
        return "jpeg"
    if raw.startswith(_GIF_MAGIC):
        return "gif"
    if raw[8:12] == _WEBP_MAGIC:
        return "webp"
    return "png"


def _image_block(image_base64: str) -> dict[str, Any] | None:
    """Turn a base64 PNG/JPEG into a Strands image content block, or ``None`` if unreadable."""
    payload = image_base64.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("intake image is not valid base64; continuing with text only")
        return None
    if not raw:
        return None
    return {"image": {"format": _image_format(raw), "source": {"bytes": raw}}}


def build_intake_task(request: AidRequest, image_base64: str | None = None) -> list[dict[str, Any]]:
    """Build the multimodal prompt for one inbound message.

    Args:
        request: The freshly created request holding the raw text and source.
        image_base64: Optional base64 PNG/JPEG of a photographed paper slip. Invalid data is
            dropped with a warning rather than failing the run.

    Returns:
        A list of Strands content blocks: the framing text, the raw message, and the image.
    """
    header = (
        f"A new request arrived (id={request.id}, source={request.source}).\n"
        "Read it, look up the requester, and return the structured intake result."
    )
    blocks: list[dict[str, Any]] = [{"text": header}]
    if image_base64:
        block = _image_block(image_base64)
        if block is not None:
            blocks.append({"text": "Attached photo of the request:"})
            blocks.append(block)
    blocks.append({"text": f"Message:\n\n{request.raw_text or '(no text; see the attached photo)'}"})
    return blocks
