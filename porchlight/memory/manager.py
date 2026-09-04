"""Wiring Porchlight's memory store into Strands' ``MemoryManager``."""

from __future__ import annotations

from typing import Any

from strands.memory import MemoryManager

from ..context import AppContext


def make_memory_manager(
    ctx: AppContext,
    *,
    injection: Any = False,
    search_tool: Any = True,
    add_tool: Any = False,
) -> MemoryManager | None:
    """Build a ``MemoryManager`` around ``ctx.memory``.

    Args:
        ctx: The app context; ``ctx.memory`` supplies the single store.
        injection: Memory context injection. Off by default so agent prompts stay deterministic
            for the demo and the tests; pass ``True`` to prepend recalled notes to every call.
        search_tool: Config for the ``search_memory`` tool the manager registers.
        add_tool: Config for the ``add_memory`` tool; off by default because Porchlight writes
            notes through its own ``remember`` tool, which also mirrors them onto the person's
            record in the store.

    Returns:
        A ``MemoryManager``, or ``None`` when the context has no memory store.
    """
    if ctx.memory is None:
        return None
    return MemoryManager(
        stores=[ctx.memory],
        search_tool_config=search_tool,
        add_tool_config=add_tool,
        injection=injection,
    )
