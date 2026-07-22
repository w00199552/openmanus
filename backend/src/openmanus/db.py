"""Topic + session storage: the collaboration registry.

Tables (all in ``sessions.db``, separate from the checkpointer's
``checkpoints.db`` which holds message *content*):

* ``topics``     — one row per task/conversation group. ``main`` is the fixed
                   default topic the entry agent lives in; every other topic is
                   created on dispatch. Owns a workdir + title.
* ``sessions``   — one row per agent execution (a single invoke/stream).
                   ``topic_id`` records which topic it belongs to (NOT NULL —
                   every session is in a topic). ``name`` is the agent name.
                   thread_id (for the LangGraph checkpointer) is NOT stored —
                   it is computed as ``f"{topic_id}:{name}"`` at build time.
* ``mailboxes``  — agent-to-agent messages (topic-scoped). [schema will be
                   updated in a later phase to use agent_name instead of
                   session_id; left as-is for now.]
* ``whiteboard`` — shared artefacts per topic. [schema will be updated in a
                   later phase; left as-is for now.]

The session/thread split: session_id identifies one execution (fresh per run);
thread_id (``topic_id:name``) identifies an agent's memory chain within a topic
and is shared across that agent's multiple sessions in the same topic.
"""

from __future__ import annotations

import aiosqlite
import json
import uuid
from pathlib import Path
from typing import Any

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
CREATE TABLE IF NOT EXISTS topics (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    workdir     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    topic_id    TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'root',
    name        TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    title       TEXT,
    model       TEXT,
    workdir     TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_topic ON sessions(topic_id);

CREATE TABLE IF NOT EXISTS mailboxes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id        TEXT NOT NULL,
    from_agent      TEXT NOT NULL,
    to_agent        TEXT NOT NULL,
    kind            TEXT NOT NULL,
    content         TEXT,
    whiteboard_ref  TEXT,
    read            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mailbox_recipient ON mailboxes(topic_id, to_agent);

CREATE TABLE IF NOT EXISTS whiteboard_note (
    id          TEXT PRIMARY KEY,
    topic_id    TEXT NOT NULL,
    author      TEXT NOT NULL,
    kind        TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    title       TEXT,
    content     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_wb_note_topic ON whiteboard_note(topic_id);
"""


async def init_db() -> None:
    """Create tables if missing. Boot-time only.

    No migrations — the new schema is incompatible with the old one (scope_id
    → topic_id). Users should delete the old sessions.db before upgrading.
    """
    Path(_db_path()).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def _row_to_session(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    try:
        d["metadata"] = json.loads(d.get("metadata") or "{}")
    except (TypeError, ValueError):
        d["metadata"] = {}
    return d


def _row_to_topic(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)


# ─── Topic store ────────────────────────────────────────────────────────────

MAIN_TOPIC_ID = "main"


class TopicStore:
    """CRUD for topics (task/conversation groups)."""

    async def _db(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(_db_path())
        db.row_factory = aiosqlite.Row
        return db

    async def create(
        self,
        *,
        topic_id: str | None = None,
        title: str | None = None,
        workdir: str | None = None,
    ) -> dict[str, Any]:
        tid = topic_id or f"topic-{uuid.uuid4().hex}"
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                """INSERT INTO topics (id, title, workdir)
                   VALUES (?, ?, ?)""",
                (tid, title, workdir or settings.workdir),
            )
            await db.commit()
        return await self.get(tid) or {"id": tid}

    async def get(self, topic_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM topics WHERE id = ?", (topic_id,)
            )
            row = await cur.fetchone()
            return _row_to_topic(row) if row else None

    async def ensure_main(self) -> dict[str, Any]:
        """Ensure the permanent 'main' topic exists; create if absent.

        'main' is the default topic where the entry agent (Manus) lives and
        handles direct user conversation. Always present, never deleted.
        """
        existing = await self.get(MAIN_TOPIC_ID)
        if existing:
            return existing
        return await self.create(
            topic_id=MAIN_TOPIC_ID, title="Main", workdir=settings.workdir,
        )

    async def update_workdir(self, topic_id: str, workdir: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                "UPDATE topics SET workdir = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (workdir, topic_id),
            )
            await db.commit()
        return await self.get(topic_id)

    async def update_title(self, topic_id: str, title: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                "UPDATE topics SET title = ?, updated_at = datetime('now') "
                "WHERE id = ?",
                (title, topic_id),
            )
            await db.commit()
        return await self.get(topic_id)

    async def list(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM topics ORDER BY updated_at DESC"
            )
            rows = await cur.fetchall()
            return [_row_to_topic(r) for r in rows]

    async def delete(self, topic_id: str) -> bool:
        """Delete a topic. 'main' cannot be deleted."""
        if topic_id == MAIN_TOPIC_ID:
            return False
        async with aiosqlite.connect(_db_path()) as db:
            cur = await db.execute(
                "DELETE FROM topics WHERE id = ?", (topic_id,)
            )
            await db.commit()
            return cur.rowcount > 0


# ─── Session store ──────────────────────────────────────────────────────────


class SessionStore:
    """Async CRUD for sessions (agent executions)."""

    async def _db(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(_db_path())
        db.row_factory = aiosqlite.Row
        return db

    async def create(
        self,
        *,
        topic_id: str,
        kind: str = "root",
        name: str | None = None,
        title: str | None = None,
        model: str | None = None,
        workdir: str | None = None,
        metadata: dict | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or f"sess-{uuid.uuid4().hex}"
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                """INSERT INTO sessions
                   (id, topic_id, kind, name, title, model, workdir, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sid,
                    topic_id,
                    kind,
                    name,
                    title,
                    model or settings.model,
                    workdir or settings.workdir,
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

    async def ensure_exists(
        self, session_id: str, *, topic_id: str, title: str | None = None
    ) -> dict[str, Any]:
        """Ensure a session with the given id exists; create if absent."""
        existing = await self.get(session_id)
        if existing:
            return existing
        return await self.create(
            session_id=session_id, topic_id=topic_id, kind="root", title=title
        )

    async def list(
        self,
        kind: str | None = None,
        topic_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List sessions, optionally filtered by kind and/or topic_id."""
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            clauses: list[str] = []
            params: list[Any] = []
            if kind:
                clauses.append("kind = ?")
                params.append(kind)
            if topic_id is not None:
                clauses.append("topic_id = ?")
                params.append(topic_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            cur = await db.execute(
                f"SELECT * FROM sessions {where} ORDER BY updated_at DESC",
                params,
            )
            rows = await cur.fetchall()
            return [_row_to_session(r) for r in rows]

    async def list_in_topic(self, topic_id: str) -> list[dict[str, Any]]:
        """All sessions in a topic, newest first."""
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM sessions WHERE topic_id = ? ORDER BY updated_at DESC",
                (topic_id,),
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
            await db.commit()
            return cur.rowcount > 0


# Module-level singletons.
topic_store = TopicStore()
session_store = SessionStore()
