"""Session storage: the participant registry + collaboration spaces.

The unified session model after the refactor. Key change: there is NO
``message_links`` edge table any more — collaboration topology is an emergent
property of mailbox messages between agent participants, not a stored graph.
Agent-to-agent communication is captured by the ``mailboxes`` table, and
shared artefacts (the "whiteboard") live in the ``whiteboard`` table.

Tables (all in ``sessions.db``, separate from the checkpointer's
``checkpoints.db`` which holds message *content*):

* ``sessions``   — nodes: each agent participant (root / team / subagent).
                   ``scope_id`` records which team-space a participant lives
                   in (NULL for top-level/root). This is spatial belonging,
                   NOT relationship topology — it answers "which room am I
                   in", not "who talked to whom".
* ``mailboxes``  — agent-to-agent messages (dispatch / result / chat). This is
                   the literal "multi-person chat" record: who sent what to
                   whom, persisted so history survives restarts and the task
                   board can be reconstructed.
* ``whiteboard`` — shared artefact space per scope (the communication layer;
                   sandbox holds the real files). Soft-structured: free
                   content + light metadata, no enforced schema.

Inspired by Claude Code (isolated agent contexts + verbatim final-message
return + filesystem-artefact pattern) and the "multi-person chat" metaphor.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

from .config import settings


def _db_path() -> str:
    """Sessions DB path, derived from DATABASE_URL (kept next to checkpoints)."""
    url = settings.database_url
    path = url
    for prefix in ("sqlite:///", "sqlite://"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    # checkpoints.db -> sessions.db (same dir)
    p = Path(path)
    return str(p.with_name("sessions.db"))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL DEFAULT 'root',
    name        TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    title       TEXT,
    model       TEXT,
    workdir     TEXT,
    scope_id    TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS mailboxes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    from_session_id TEXT NOT NULL,
    kind            TEXT NOT NULL,
    content         TEXT,
    whiteboard_ref  TEXT,
    read            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mailbox_session ON mailboxes(session_id);
CREATE INDEX IF NOT EXISTS idx_mailbox_from    ON mailboxes(from_session_id);

CREATE TABLE IF NOT EXISTS whiteboard (
    id          TEXT PRIMARY KEY,
    scope_id    TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    kind        TEXT,
    title       TEXT,
    content     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_whiteboard_scope   ON whiteboard(scope_id);
CREATE INDEX IF NOT EXISTS idx_whiteboard_session ON whiteboard(session_id);
"""

# Boot-time migrations. Each entry is (statements, probe): the probe runs first;
# if it raises OperationalError the column/table is missing so we run the
# statements. New databases already have everything from _SCHEMA, so the probes
# succeed and migrations are skipped. ``CREATE INDEX IF NOT EXISTS`` is safe to
# run unconditionally inside the migration block (after the column exists).
_MIGRATIONS = [
    (
        # v1: introduce scope_id on sessions (replaces message_links graph).
        [
            "ALTER TABLE sessions ADD COLUMN scope_id TEXT",
            "CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope_id)",
        ],
        "SELECT scope_id FROM sessions LIMIT 1",
    ),
    (
        # v2: drop the obsolete message_links table if it still exists.
        ["DROP TABLE IF EXISTS message_links"],
        "SELECT id FROM message_links LIMIT 1",
    ),
]


async def init_db() -> None:
    """Create tables if missing + apply idempotent migrations. Boot-time only."""
    Path(_db_path()).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript(_SCHEMA)
        # Apply migrations idempotently. Each migration probes for the target
        # object; if the probe raises OperationalError it's missing → run the
        # statements. Each statement is individually try/excepted so a partial
        # apply is tolerated.
        for statements, probe in _MIGRATIONS:
            missing = False
            try:
                cur = await db.execute(probe)
                await cur.fetchone()
            except aiosqlite.OperationalError:
                missing = True
            if not missing:
                continue
            for stmt in statements:
                try:
                    await db.execute(stmt)
                except aiosqlite.OperationalError:
                    pass  # already done by a concurrent path / older run
        await db.commit()


def _row_to_session(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["metadata"] = json.loads(d.get("metadata") or "{}")
    except (TypeError, ValueError):
        d["metadata"] = {}
    return d


class SessionStore:
    """Async CRUD + graph queries for sessions and their message links."""

    async def _db(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(_db_path())
        db.row_factory = aiosqlite.Row
        return db

    async def create(
        self,
        *,
        kind: str = "root",
        name: str | None = None,
        title: str | None = None,
        model: str | None = None,
        workdir: str | None = None,
        scope_id: str | None = None,
        metadata: dict | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or f"sess-{uuid.uuid4().hex}"
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                """INSERT INTO sessions
                   (id, kind, name, title, model, workdir, scope_id, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sid,
                    kind,
                    name,
                    title,
                    model or settings.model,
                    workdir or settings.workdir,
                    scope_id,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            await db.commit()
        return await self.get(sid) or {"id": sid}

    async def get(self, session_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            )
            row = await cur.fetchone()
            return _row_to_session(row) if row else None

    async def ensure_manus(self) -> dict[str, Any]:
        """Ensure the permanent entry session (Manus) exists; create if absent.

        Uses a fixed id ("manus") so the entry is a singleton: always present,
        never deleted. "New chat" resets its history (clears the checkpointer
        thread). Idempotent across restarts. Also migrates the legacy "default"
        id to "manus" if the old row exists.
        """
        # migrate legacy "default" → "manus"
        legacy = await self.get("default")
        if legacy and not await self.get("manus"):
            async with aiosqlite.connect(_db_path()) as db:
                await db.execute(
                    "UPDATE sessions SET id = ? WHERE id = ?", ("manus", "default")
                )
                await db.commit()
        existing = await self.get("manus")
        if existing:
            if existing.get("title") != "Manus":
                return await self.update("manus", title="Manus")
            return existing
        return await self.create(session_id="manus", kind="root", title="Manus")

    async def ensure_exists(
        self, session_id: str, *, title: str | None = None
    ) -> dict[str, Any]:
        """Ensure a session with the given id exists; create if absent."""
        existing = await self.get(session_id)
        if existing:
            return existing
        return await self.create(session_id=session_id, kind="root", title=title)

    async def list(
        self,
        kind: str | None = None,
        scope_id: str | None = ...,
    ) -> list[dict[str, Any]]:
        """List sessions, optionally filtered by kind and/or scope_id.

        ``scope_id`` uses a sentinel default (``...``) to distinguish "not
        provided" from "explicitly None" (NULL = top-level). When the sentinel
        is passed the scope filter is skipped; when ``None`` is passed
        explicitly only top-level (scope_id IS NULL) sessions are returned.
        """
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            clauses: list[str] = []
            params: list[Any] = []
            if kind:
                clauses.append("kind = ?")
                params.append(kind)
            if scope_id is not ...:
                if scope_id is None:
                    clauses.append("scope_id IS NULL")
                else:
                    clauses.append("scope_id = ?")
                    params.append(scope_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            cur = await db.execute(
                f"SELECT * FROM sessions {where} ORDER BY updated_at DESC",
                params,
            )
            rows = await cur.fetchall()
            return [_row_to_session(r) for r in rows]

    async def list_in_scope(self, scope_id: str) -> list[dict[str, Any]]:
        """All participant sessions living in a team-space (scope_id match).

        This is the O(1) indexed answer to "which agents are in this room",
        i.e. the members of a scope. Excludes the scope session itself.
        """
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM sessions WHERE scope_id = ? ORDER BY updated_at DESC",
                (scope_id,),
            )
            rows = await cur.fetchall()
            return [_row_to_session(r) for r in rows]

    async def update(
        self,
        session_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        workdir: str | None = None,
        metadata: dict | None = None,
        touch: bool = True,
    ) -> dict[str, Any] | None:
        sets: list[str] = []
        params: list[Any] = []
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if workdir is not None:
            sets.append("workdir = ?")
            params.append(workdir)
        if metadata is not None:
            sets.append("metadata = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))
        if touch:
            sets.append("updated_at = datetime('now')")
        if not sets:
            return await self.get(session_id)
        params.append(session_id)
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params
            )
            await db.commit()
        return await self.get(session_id)

    async def delete(self, session_id: str) -> bool:
        async with aiosqlite.connect(_db_path()) as db:
            cur = await db.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            # Clean up the participant's mailbox + whiteboard artefacts too.
            await db.execute(
                "DELETE FROM mailboxes WHERE session_id = ? OR from_session_id = ?",
                (session_id, session_id),
            )
            await db.execute(
                "DELETE FROM whiteboard WHERE session_id = ?", (session_id,)
            )
            await db.commit()
            return cur.rowcount > 0


# Module-level singleton (created once; cheap to reconnect per-op with aiosqlite).
session_store = SessionStore()
