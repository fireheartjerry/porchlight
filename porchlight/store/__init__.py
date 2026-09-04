"""Storage backends. ``make_store(settings)`` picks one from configuration."""

from __future__ import annotations

from ..config import Settings
from .base import Store
from .dynamo_store import DynamoStore
from .sqlite_store import SqliteStore

__all__ = ["DynamoStore", "SqliteStore", "Store", "make_store"]


def make_store(settings: Settings) -> Store:
    """Return the store configured by ``settings.store``.

    Args:
        settings: Application settings.

    Returns:
        A :class:`SqliteStore` or :class:`DynamoStore`; neither touches AWS at import time.
    """
    if settings.store == "dynamo":
        return DynamoStore(table=settings.dynamo_table, region=settings.aws_region)
    return SqliteStore(settings.sqlite_path)
