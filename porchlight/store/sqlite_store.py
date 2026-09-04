"""SQLite-backed :class:`~porchlight.store.base.Store` — the default for local runs and tests."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..models import (
    AidRequest,
    Attempt,
    Decision,
    DecisionStatus,
    GroupSettings,
    LogEvent,
    MessageStatus,
    OutboundMessage,
    Requester,
    RequestStatus,
    Volunteer,
)
from .base import StaleVersionError, apply_fields, trace_row

M = TypeVar("M", bound=BaseModel)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS volunteers (
    id TEXT PRIMARY KEY,
    vetted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_volunteers_vetted ON volunteers(vetted);
CREATE INDEX IF NOT EXISTS idx_volunteers_created_at ON volunteers(created_at);

CREATE TABLE IF NOT EXISTS requesters (
    id TEXT PRIMARY KEY,
    contact TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requesters_contact ON requesters(contact);
CREATE INDEX IF NOT EXISTS idx_requesters_created_at ON requesters(created_at);

CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    requester_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests(created_at);
CREATE INDEX IF NOT EXISTS idx_requests_updated_at ON requests(updated_at);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    request_id TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_decisions_request_id ON decisions(request_id);
CREATE INDEX IF NOT EXISTS idx_decisions_created_at ON decisions(created_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    request_id TEXT,
    scheduled_for TEXT,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_request_id ON messages(request_id);
CREATE INDEX IF NOT EXISTS idx_messages_scheduled_for ON messages(scheduled_for);

CREATE TABLE IF NOT EXISTS log (
    id TEXT PRIMARY KEY,
    request_id TEXT,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_log_request_id ON log(request_id);
CREATE INDEX IF NOT EXISTS idx_log_created_at ON log(created_at);

CREATE TABLE IF NOT EXISTS trace (
    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    request_id TEXT,
    expires_at INTEGER NOT NULL DEFAULT 0,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_request_id ON trace(request_id);
CREATE INDEX IF NOT EXISTS idx_trace_expires_at ON trace(expires_at);

CREATE TABLE IF NOT EXISTS group_settings (
    id TEXT PRIMARY KEY,
    body TEXT NOT NULL
);
"""

_TABLES = (
    "volunteers",
    "requesters",
    "requests",
    "decisions",
    "messages",
    "log",
    "trace",
    "group_settings",
)


def _iso(value: datetime | None) -> str | None:
    """Normalize a datetime to a sortable UTC ISO string."""
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


class SqliteStore:
    """Thread-safe SQLite store: one table per entity, JSON body plus indexed columns.

    Args:
        path: Database file path, or ``":memory:"`` for an ephemeral database.
    """

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self.path = str(Path(path).expanduser())
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._migrate()
            self._conn.commit()

    # --- plumbing -----------------------------------------------------------

    def _migrate(self) -> None:
        """Bring an older database file up to the current schema (caller holds the lock)."""
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(requests)")}
        if "version" not in columns:
            self._conn.execute("ALTER TABLE requests ADD COLUMN version INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        """Close the underlying connection."""
        with self._lock:
            self._conn.close()

    def _write(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def _one(self, model: type[M], table: str, id: str) -> M | None:
        rows = self._rows(f"SELECT body FROM {table} WHERE id = ?", (id,))
        return model.model_validate_json(rows[0]["body"]) if rows else None

    @staticmethod
    def _load(model: type[M], rows: list[sqlite3.Row]) -> list[M]:
        return [model.model_validate_json(row["body"]) for row in rows]

    # --- volunteers ---------------------------------------------------------

    def put_volunteer(self, v: Volunteer) -> Volunteer:
        """Insert or replace a volunteer and return it."""
        self._write(
            "INSERT OR REPLACE INTO volunteers (id, vetted, created_at, body) VALUES (?, ?, ?, ?)",
            (v.id, int(v.vetted), _iso(v.created_at), v.model_dump_json()),
        )
        return v

    def get_volunteer(self, id: str) -> Volunteer | None:
        """Return the volunteer with this id, or ``None``."""
        return self._one(Volunteer, "volunteers", id)

    def list_volunteers(
        self, zone: str | None = None, skill: str | None = None, vetted: bool | None = None
    ) -> list[Volunteer]:
        """List volunteers, optionally filtered by zone, skill, and vetted flag."""
        sql = "SELECT body FROM volunteers"
        params: tuple[Any, ...] = ()
        if vetted is not None:
            sql += " WHERE vetted = ?"
            params = (int(vetted),)
        sql += " ORDER BY created_at ASC"
        volunteers = self._load(Volunteer, self._rows(sql, params))
        if zone is not None:
            volunteers = [v for v in volunteers if zone in v.zones]
        if skill is not None:
            needle = skill.lower()
            volunteers = [v for v in volunteers if any(s.lower().startswith(needle) for s in v.skills)]
        return volunteers

    # --- requesters ---------------------------------------------------------

    def put_requester(self, r: Requester) -> Requester:
        """Insert or replace a requester and return it."""
        self._write(
            "INSERT OR REPLACE INTO requesters (id, contact, created_at, body) VALUES (?, ?, ?, ?)",
            (r.id, r.contact.lower(), _iso(r.first_seen), r.model_dump_json()),
        )
        return r

    def get_requester(self, id: str) -> Requester | None:
        """Return the requester with this id, or ``None``."""
        return self._one(Requester, "requesters", id)

    def find_requester_by_contact(self, contact: str) -> Requester | None:
        """Return the requester whose contact matches (case-insensitive), or ``None``."""
        rows = self._rows("SELECT body FROM requesters WHERE contact = ? LIMIT 1", (contact.lower(),))
        return Requester.model_validate_json(rows[0]["body"]) if rows else None

    def list_requesters(self) -> list[Requester]:
        """List every requester, newest first."""
        return self._load(Requester, self._rows("SELECT body FROM requesters ORDER BY created_at DESC"))

    # --- requests -----------------------------------------------------------

    def put_request(self, req: AidRequest) -> AidRequest:
        """Insert or replace an aid request and return it."""
        self._write(_UPSERT_REQUEST, _request_row(req))
        return req

    def get_request(self, id: str) -> AidRequest | None:
        """Return the aid request with this id, or ``None``."""
        return self._one(AidRequest, "requests", id)

    def list_requests(self, status: RequestStatus | None = None, limit: int = 200) -> list[AidRequest]:
        """List aid requests, newest first, optionally filtered by status."""
        if status is not None:
            sql = "SELECT body FROM requests WHERE status = ? ORDER BY created_at DESC LIMIT ?"
            params: tuple[Any, ...] = (str(status), limit)
        else:
            sql = "SELECT body FROM requests ORDER BY created_at DESC LIMIT ?"
            params = (limit,)
        return self._load(AidRequest, self._rows(sql, params))

    def requests_for_volunteer(self, volunteer_id: str, since: datetime) -> list[AidRequest]:
        """Requests created since ``since`` that this volunteer was asked about or assigned."""
        rows = self._rows(
            "SELECT body FROM requests WHERE created_at >= ? ORDER BY created_at DESC", (_iso(since),)
        )
        return [
            req
            for req in self._load(AidRequest, rows)
            if req.assigned_volunteer_id == volunteer_id or volunteer_id in req.attempted_volunteer_ids()
        ]

    def update_request_fields(
        self, request_id: str, *, expected_version: int | None = None, **fields: Any
    ) -> AidRequest | None:
        """Atomically write a few fields of one request (see :class:`.base.Store`).

        The whole read-modify-write happens under the store lock and commits with a single
        ``UPDATE ... WHERE id = ? AND version = ?``, so two threads updating different fields of
        the same request can never lose one another's work.
        """
        with self._lock:
            return self._mutate(request_id, lambda req: apply_fields(req, fields), expected_version)

    def append_attempt(self, request_id: str, attempt: Attempt) -> AidRequest | None:
        """Atomically append one outreach attempt (see :class:`.base.Store`)."""
        with self._lock:
            return self._mutate(request_id, lambda req: _with_attempts(req, [*req.attempts, attempt]))

    def resolve_attempt(self, request_id: str, attempt: Attempt) -> AidRequest | None:
        """Settle this volunteer's open attempt, or append it (see :class:`.base.Store`)."""
        with self._lock:
            return self._mutate(request_id, lambda req: _with_attempts(req, _settled(req, attempt)))

    def _mutate(
        self,
        request_id: str,
        change: Callable[[AidRequest], AidRequest],
        expected_version: int | None = None,
    ) -> AidRequest | None:
        """Apply ``change`` to one stored request and write it back conditionally.

        The caller must already hold ``self._lock``.
        """
        rows = list(self._conn.execute("SELECT body, version FROM requests WHERE id = ?", (request_id,)))
        if not rows:
            return None
        current = AidRequest.model_validate_json(rows[0]["body"])
        stored_version = int(rows[0]["version"] if rows[0]["version"] is not None else current.version)
        if expected_version is not None and expected_version != stored_version:
            raise StaleVersionError(request_id, expected_version, stored_version)
        updated = change(current)
        updated.version = stored_version + 1
        _id, *columns = _request_row(updated)
        cursor = self._conn.execute(
            "UPDATE requests SET status = ?, requester_id = ?, created_at = ?, updated_at = ?,"
            " version = ?, body = ? WHERE id = ? AND version = ?",
            (*columns, request_id, stored_version),
        )
        if cursor.rowcount == 0:  # pragma: no cover - the lock makes this unreachable in-process
            raise StaleVersionError(request_id, stored_version, None)
        self._conn.commit()
        return updated

    # --- decisions ----------------------------------------------------------

    def put_decision(self, d: Decision) -> Decision:
        """Insert or replace a decision card and return it."""
        self._write(
            "INSERT OR REPLACE INTO decisions (id, status, request_id, created_at, resolved_at, body)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                d.id,
                str(d.status),
                d.request_id,
                _iso(d.created_at),
                _iso(d.resolved_at),
                d.model_dump_json(),
            ),
        )
        return d

    def get_decision(self, id: str) -> Decision | None:
        """Return the decision card with this id, or ``None``."""
        return self._one(Decision, "decisions", id)

    def list_decisions(self, status: DecisionStatus | None = None) -> list[Decision]:
        """List decision cards, newest first, optionally filtered by status."""
        if status is not None:
            rows = self._rows(
                "SELECT body FROM decisions WHERE status = ? ORDER BY created_at DESC", (str(status),)
            )
        else:
            rows = self._rows("SELECT body FROM decisions ORDER BY created_at DESC")
        return self._load(Decision, rows)

    # --- messages -----------------------------------------------------------

    def put_message(self, m: OutboundMessage) -> OutboundMessage:
        """Insert or replace an outbound message and return it."""
        self._write(
            "INSERT OR REPLACE INTO messages (id, status, request_id, scheduled_for, created_at, body)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                m.id,
                str(m.status),
                m.request_id,
                _iso(m.scheduled_for),
                _iso(m.created_at),
                m.model_dump_json(),
            ),
        )
        return m

    def list_messages(
        self,
        request_id: str | None = None,
        status: MessageStatus | None = None,
        due_before: datetime | None = None,
    ) -> list[OutboundMessage]:
        """List outbound messages, newest first; ``due_before`` filters on ``scheduled_for``."""
        clauses: list[str] = []
        params: list[Any] = []
        if request_id is not None:
            clauses.append("request_id = ?")
            params.append(request_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(str(status))
        if due_before is not None:
            clauses.append("scheduled_for IS NOT NULL AND scheduled_for <= ?")
            params.append(_iso(due_before))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._rows(f"SELECT body FROM messages{where} ORDER BY created_at DESC", tuple(params))
        return self._load(OutboundMessage, rows)

    # --- log ----------------------------------------------------------------

    def append_log(self, e: LogEvent) -> LogEvent:
        """Append a quiet-log event and return it."""
        self._write(
            "INSERT OR REPLACE INTO log (id, request_id, created_at, body) VALUES (?, ?, ?, ?)",
            (e.id, e.request_id, _iso(e.ts), e.model_dump_json()),
        )
        return e

    def list_log(
        self, request_id: str | None = None, limit: int = 200, since: datetime | None = None
    ) -> list[LogEvent]:
        """List quiet-log events, newest first."""
        clauses: list[str] = []
        params: list[Any] = []
        if request_id is not None:
            clauses.append("request_id = ?")
            params.append(request_id)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(_iso(since))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._rows(
            f"SELECT body FROM log{where} ORDER BY created_at DESC, id DESC LIMIT ?", tuple(params)
        )
        return self._load(LogEvent, rows)

    # --- trace --------------------------------------------------------------

    def append_trace(self, event: dict[str, Any]) -> int:
        """Persist one trace event and return its cursor (see :class:`.base.Store`)."""
        row = trace_row(event, datetime.now(UTC))
        request_id = row.get("request_id")
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO trace (ts, request_id, expires_at, body) VALUES (?, ?, ?, ?)",
                (
                    str(row["ts"]),
                    request_id if isinstance(request_id, str) else None,
                    int(row["expires_at"]),
                    json.dumps(row),
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid or 0)

    def list_trace(
        self, since_cursor: int = 0, limit: int = 500, request_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Read trace events after ``since_cursor``, oldest first (see :class:`.base.Store`)."""
        clauses = ["cursor > ?"]
        params: list[Any] = [int(since_cursor)]
        if request_id is not None:
            clauses.append("request_id = ?")
            params.append(request_id)
        params.append(max(0, int(limit)))
        rows = self._rows(
            f"SELECT cursor, body FROM trace WHERE {' AND '.join(clauses)} ORDER BY cursor ASC LIMIT ?",
            tuple(params),
        )
        return [{**json.loads(row["body"]), "cursor": int(row["cursor"])} for row in rows]

    # --- settings -----------------------------------------------------------

    def get_group_settings(self) -> GroupSettings:
        """Return the stored group settings, or defaults when none were saved."""
        rows = self._rows("SELECT body FROM group_settings WHERE id = 'singleton'")
        return GroupSettings.model_validate_json(rows[0]["body"]) if rows else GroupSettings()

    def put_group_settings(self, gs: GroupSettings) -> GroupSettings:
        """Persist the group settings and return them."""
        self._write(
            "INSERT OR REPLACE INTO group_settings (id, body) VALUES ('singleton', ?)",
            (gs.model_dump_json(),),
        )
        return gs

    # --- util ---------------------------------------------------------------

    def reset(self) -> None:
        """Wipe every table (tests and demo reseeding)."""
        with self._lock:
            for table in _TABLES:
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()

    def stats(self, day: date) -> dict[str, Any]:
        """Counters for the UTC day ``day``.

        ``handled_autonomously`` counts requests touched that day that reached a confirmed or
        finished state without ever raising a decision card.
        """
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)
        rows = self._rows(
            "SELECT body FROM requests WHERE updated_at >= ? AND updated_at < ?", (_iso(start), _iso(end))
        )
        touched = self._load(AidRequest, rows)

        requests_by_status: dict[str, int] = {}
        for req in touched:
            key = str(req.status)
            requests_by_status[key] = requests_by_status.get(key, 0) + 1

        flagged = {
            row["request_id"]
            for row in self._rows("SELECT DISTINCT request_id FROM decisions WHERE request_id IS NOT NULL")
        }
        settled = {
            RequestStatus.CONFIRMED,
            RequestStatus.IN_PROGRESS,
            RequestStatus.COMPLETED,
        }
        handled = sum(1 for req in touched if req.status in settled and req.id not in flagged)

        decisions_open = self._rows("SELECT COUNT(*) AS n FROM decisions WHERE status = 'open'")[0]["n"]
        decisions_resolved = self._rows(
            "SELECT COUNT(*) AS n FROM decisions WHERE status = 'resolved'"
            " AND resolved_at >= ? AND resolved_at < ?",
            (_iso(start), _iso(end)),
        )[0]["n"]

        return {
            "handled_autonomously": handled,
            "decisions_open": int(decisions_open),
            "decisions_resolved": int(decisions_resolved),
            "requests_by_status": requests_by_status,
        }

    def __repr__(self) -> str:
        return f"SqliteStore(path={self.path!r})"


_UPSERT_REQUEST = (
    "INSERT OR REPLACE INTO requests (id, status, requester_id, created_at, updated_at, version, body)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)


def _request_row(req: AidRequest) -> tuple[Any, ...]:
    """The indexed columns plus the JSON body for one request."""
    return (
        req.id,
        str(req.status),
        req.requester_id,
        _iso(req.created_at),
        _iso(req.updated_at),
        int(req.version),
        req.model_dump_json(),
    )


def _with_attempts(req: AidRequest, attempts: list[Attempt]) -> AidRequest:
    """A copy of ``req`` carrying exactly ``attempts``, with nothing else touched."""
    return req.model_copy(update={"attempts": list(attempts)})


def _settled(req: AidRequest, attempt: Attempt) -> list[Attempt]:
    """``req.attempts`` with this volunteer's open attempt settled, or ``attempt`` appended."""
    attempts = list(req.attempts)
    for index in range(len(attempts) - 1, -1, -1):
        candidate = attempts[index]
        if candidate.volunteer_id == attempt.volunteer_id and candidate.outcome == "pending":
            attempts[index] = candidate.model_copy(update={"outcome": attempt.outcome, "note": attempt.note})
            return attempts
    attempts.append(attempt)
    return attempts
