"""A local ``strands.memory.MemoryStore`` backed by SQLite FTS5.

Porchlight's long-term memory is small, human-readable, and needs to survive a laptop restart:
"Mr. Okafor prefers Maria", "Devon only does weekends". SQLite's FTS5 full-text index with BM25
ranking gives good-enough recall with no embeddings, no network, and no AWS account.

The Strands protocol is async; every method here also has a ``*_sync`` twin because Porchlight's
tools are synchronous functions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strands.memory.types import AddMessagesContext, MemoryEntry, SearchOptions
from strands.types.content import Message

from ..clock import Clock, SystemClock
from ..ids import new_id

logger = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    about_id TEXT,
    kind TEXT NOT NULL DEFAULT 'fact',
    ts TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_about ON memory_entries(about_id);
CREATE INDEX IF NOT EXISTS idx_memory_ts ON memory_entries(ts);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    about_id,
    kind,
    entry_id UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _quote_token(token: str) -> str:
    """Quote one FTS5 term so punctuation in user text cannot become query syntax."""
    return '"' + token.replace('"', '""') + '"'


def _match_query(query: str) -> str | None:
    """Turn free text into a safe FTS5 ``MATCH`` expression, or ``None`` when there is nothing to match."""
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in query).split() if len(t) > 1]
    if not tokens:
        return None
    return " OR ".join(_quote_token(t) for t in tokens[:24])


class SqliteMemoryStore:
    """Durable notes with full-text search.

    Args:
        path: SQLite file to use, or ``":memory:"``. Shares the file with the main store safely.
        name: Store name, as required by the Strands ``MemoryStore`` protocol.
        description: Shown to the model in memory tool descriptions.
        max_search_results: Default result cap for :meth:`search`.
        writable: Whether the manager may write to this store.
        extraction: Automatic-extraction config (``False`` by default: Porchlight writes notes
            explicitly through the ``remember`` tool rather than distilling every conversation).
        clock: Time source for entry timestamps.
    """

    def __init__(
        self,
        path: str = ":memory:",
        *,
        name: str = "porchlight_memory",
        description: str = (
            "Durable neighbourhood notes: volunteer preferences, requester facts, and how past jobs went."
        ),
        max_search_results: int = DEFAULT_MAX_RESULTS,
        writable: bool = True,
        extraction: Any = False,
        clock: Clock | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.max_search_results = max_search_results
        self.writable = writable
        self.extraction = extraction
        self._clock = clock or SystemClock()
        self.path = path
        if path != ":memory:":
            resolved = Path(path).expanduser()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(resolved)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.fts_enabled = True
        self._ensure_schema()

    # --- plumbing -----------------------------------------------------------

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            try:
                self._conn.executescript(_FTS_SCHEMA)
            except sqlite3.OperationalError:  # pragma: no cover - FTS5 is standard on CPython
                logger.warning("SQLite built without FTS5; memory search falls back to LIKE")
                self.fts_enabled = False
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            self._conn.close()

    def __repr__(self) -> str:
        return f"SqliteMemoryStore(name={self.name!r}, path={self.path!r}, entries={self.count()})"

    def count(self) -> int:
        """Number of stored entries."""
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) AS n FROM memory_entries").fetchone()["n"])

    def reset(self) -> None:
        """Delete every entry (tests and demo reseeding)."""
        with self._lock:
            self._conn.execute("DELETE FROM memory_entries")
            if self.fts_enabled:
                self._conn.execute("DELETE FROM memory_fts")
            self._conn.commit()

    # --- writing ------------------------------------------------------------

    def add_sync(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """Store one note and return its id.

        Args:
            content: The note, in plain English.
            metadata: Free-form metadata; ``about_id`` and ``kind`` are promoted to columns.
        """
        text = (content or "").strip()
        if not text:
            raise ValueError("memory content must not be empty")
        meta = dict(metadata or {})
        about_id = meta.get("about_id")
        kind = str(meta.get("kind") or "fact")
        ts = meta.get("ts") or self._clock.now().isoformat()
        meta.update({"about_id": about_id, "kind": kind, "ts": ts})
        entry_id = str(meta.get("id") or new_id("mem"))
        meta["id"] = entry_id
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO memory_entries (id, content, about_id, kind, ts, metadata)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (entry_id, text, about_id, kind, ts, json.dumps(meta, default=str)),
            )
            if self.fts_enabled:
                self._conn.execute("DELETE FROM memory_fts WHERE entry_id = ?", (entry_id,))
                self._conn.execute(
                    "INSERT INTO memory_fts (content, about_id, kind, entry_id) VALUES (?, ?, ?, ?)",
                    (text, about_id or "", kind, entry_id),
                )
            self._conn.commit()
        return entry_id

    async def add(self, content: str, metadata: dict[str, Any] | None = None) -> str:
        """Strands ``MemoryStore.add``: store one note and return its id."""
        return self.add_sync(content, metadata)

    def add_messages_sync(
        self, messages: list[Message], context: AddMessagesContext | None = None
    ) -> list[str]:
        """Store the text of a batch of conversation messages, preserving roles."""
        numbers = list(getattr(context, "sequence_numbers", None) or [])
        ids: list[str] = []
        for index, message in enumerate(messages):
            text = " ".join(
                block["text"] for block in message.get("content", []) if isinstance(block.get("text"), str)
            ).strip()
            if not text:
                continue
            seq = numbers[index] if index < len(numbers) else index
            ids.append(
                self.add_sync(
                    text,
                    {"kind": "message", "role": message.get("role"), "sequence": seq},
                )
            )
        return ids

    async def add_messages(
        self, messages: list[Message], context: AddMessagesContext | None = None
    ) -> list[str]:
        """Strands ``MemoryStore.add_messages``: ingest a batch of conversation messages."""
        return self.add_messages_sync(messages, context)

    # --- reading ------------------------------------------------------------

    def search_sync(
        self, query: str, limit: int | None = None, about: str | None = None
    ) -> list[MemoryEntry]:
        """Search notes by relevance (BM25), newest first among equals.

        Args:
            query: Free text; punctuation is ignored, terms are OR-ed.
            limit: Maximum results; defaults to ``max_search_results``.
            about: Restrict to notes about one volunteer or requester id.
        """
        cap = max(1, limit or self.max_search_results or DEFAULT_MAX_RESULTS)
        match = _match_query(query or "")
        rows: list[sqlite3.Row]
        if self.fts_enabled and match:
            sql = (
                "SELECT e.id, e.content, e.about_id, e.kind, e.ts, e.metadata,"
                " bm25(memory_fts, 1.0, 0.4, 0.2, 0.0) AS rank"
                " FROM memory_fts JOIN memory_entries e ON e.id = memory_fts.entry_id"
                " WHERE memory_fts MATCH ?"
            )
            params: list[Any] = [match]
            if about:
                sql += " AND e.about_id = ?"
                params.append(about)
            sql += " ORDER BY rank ASC, e.ts DESC LIMIT ?"
            params.append(cap)
            with self._lock:
                rows = list(self._conn.execute(sql, tuple(params)).fetchall())
        else:
            sql = "SELECT id, content, about_id, kind, ts, metadata, 0.0 AS rank FROM memory_entries"
            clauses: list[str] = []
            params = []
            if about:
                clauses.append("about_id = ?")
                params.append(about)
            if query:
                clauses.append("content LIKE ?")
                params.append(f"%{query.strip()}%")
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY ts DESC LIMIT ?"
            params.append(cap)
            with self._lock:
                rows = list(self._conn.execute(sql, tuple(params)).fetchall())
        return [self._to_entry(row) for row in rows]

    async def search(self, query: str, options: SearchOptions | None = None) -> list[MemoryEntry]:
        """Strands ``MemoryStore.search``.

        Recognises the standard ``max_search_results`` option plus a Porchlight-specific
        ``about`` option that scopes results to one person's id.
        """
        opts: dict[str, Any] = dict(options or {})
        return self.search_sync(
            query,
            limit=opts.get("max_search_results"),
            about=opts.get("about"),
        )

    async def initialize(self) -> None:
        """Strands ``MemoryStore.initialize``: make sure the schema exists."""
        self._ensure_schema()

    def recent(self, limit: int = 20, about: str | None = None) -> list[MemoryEntry]:
        """Most recent notes, newest first (used by the UI and tests)."""
        sql = "SELECT id, content, about_id, kind, ts, metadata, 0.0 AS rank FROM memory_entries"
        params: list[Any] = []
        if about:
            sql += " WHERE about_id = ?"
            params.append(about)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(max(1, limit))
        with self._lock:
            rows = list(self._conn.execute(sql, tuple(params)).fetchall())
        return [self._to_entry(row) for row in rows]

    def _to_entry(self, row: sqlite3.Row) -> MemoryEntry:
        try:
            metadata = json.loads(row["metadata"])
        except (TypeError, ValueError):  # pragma: no cover - defensive
            metadata = {}
        metadata.update(
            {
                "id": row["id"],
                "about_id": row["about_id"],
                "kind": row["kind"],
                "ts": row["ts"],
                "score": round(-float(row["rank"]), 6),
            }
        )
        return MemoryEntry(content=row["content"], store_name=self.name, metadata=metadata)


def utc_iso(moment: datetime) -> str:
    """ISO-8601 in UTC (helper for callers building metadata by hand)."""
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()
