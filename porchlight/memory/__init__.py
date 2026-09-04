"""Porchlight's long-term memory: a SQLite store locally, AgentCore Memory on AWS.

Both stores implement the async ``strands.memory.MemoryStore`` protocol *and* expose synchronous
twins, because Porchlight's tools are ordinary functions. :func:`search_memory` and
:func:`add_memory` pick whichever is available, so a third-party ``MemoryStore`` still works.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from strands.memory.types import MemoryEntry

from ..config import Settings
from .agentcore_store import AgentCoreMemoryStore
from .sqlite_store import SqliteMemoryStore

logger = logging.getLogger(__name__)

__all__ = [
    "AgentCoreMemoryStore",
    "MemoryEntry",
    "SqliteMemoryStore",
    "add_memory",
    "entry_to_dict",
    "make_memory_store",
    "run_sync",
    "search_memory",
]


def make_memory_store(settings: Settings) -> SqliteMemoryStore | AgentCoreMemoryStore | None:
    """Build the memory store configured by ``settings``.

    AgentCore Memory is used when a ``memory_id`` is configured and the mode is ``live``;
    otherwise notes live in the local SQLite database next to the rest of the demo data.
    """
    if not settings.is_demo and settings.memory_id:
        return AgentCoreMemoryStore(memory_id=settings.memory_id, region=settings.aws_region)
    return SqliteMemoryStore(settings.sqlite_path)


def run_sync(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run ``coro`` to completion from synchronous code, even inside a running event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def entry_to_dict(entry: Any) -> dict[str, Any]:
    """Normalize a store result (``MemoryEntry``, dict, or string) to the tool contract shape."""
    if isinstance(entry, dict):
        return {"content": str(entry.get("content", "")), "metadata": dict(entry.get("metadata") or {})}
    content = getattr(entry, "content", None)
    if content is None:
        return {"content": str(entry), "metadata": {}}
    metadata = dict(getattr(entry, "metadata", None) or {})
    store_name = getattr(entry, "store_name", None)
    if store_name:
        metadata.setdefault("store", store_name)
    return {"content": str(content), "metadata": metadata}


def search_memory(
    store: Any, query: str, *, about: str | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Search any ``MemoryStore``, preferring its synchronous twin.

    Args:
        store: A memory store, or ``None``.
        query: What to recall.
        about: Restrict to notes about one volunteer or requester id.
        limit: Maximum results.

    Returns:
        ``[{"content": str, "metadata": {...}}]``; empty when there is no store or the backend
        fails (memory is an enhancement, never a hard dependency).
    """
    if store is None:
        return []
    try:
        sync = getattr(store, "search_sync", None)
        if callable(sync):
            results = sync(query, limit=limit, about=about)
        else:
            options: dict[str, Any] = {}
            if limit is not None:
                options["max_search_results"] = limit
            if about is not None:
                options["about"] = about
            results = run_sync(store.search(query, options or None))
    except Exception:
        logger.warning("memory search failed", exc_info=True)
        return []
    return [entry_to_dict(item) for item in results or []]


def add_memory(store: Any, content: str, metadata: dict[str, Any] | None = None) -> bool:
    """Write one note to any ``MemoryStore``, preferring its synchronous twin.

    Returns:
        True when the note was stored.
    """
    if store is None:
        return False
    try:
        sync = getattr(store, "add_sync", None)
        if callable(sync):
            sync(content, metadata)
        else:
            run_sync(store.add(content, metadata))
    except Exception:
        logger.warning("memory write failed", exc_info=True)
        return False
    return True
