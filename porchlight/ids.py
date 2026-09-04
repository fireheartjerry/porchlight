"""Prefixed, URL-safe identifiers used across Porchlight entities."""

from __future__ import annotations

import secrets

ID_HEX_CHARS = 10
"""Number of hex characters appended after the prefix."""


def new_id(prefix: str) -> str:
    """Return a new id of the form ``<prefix>_<10 hex chars>``.

    Args:
        prefix: Short entity prefix, e.g. ``"req"``, ``"vol"``, ``"rqr"``, ``"dec"``, ``"msg"``, ``"log"``.

    Returns:
        A random identifier, e.g. ``"req_9f3a1c04bd"``.
    """
    if not prefix or "_" in prefix:
        raise ValueError(f"invalid id prefix: {prefix!r}")
    return f"{prefix}_{secrets.token_hex(ID_HEX_CHARS // 2)}"
