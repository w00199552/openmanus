"""Whiteboard: the topic-scoped task board.

A flat, soft-structured list of notes attached to a topic. Each note records
who wrote it (``author``), a free-form ``kind`` tag the agent picks (task /
plan / research / result / …), a workflow ``status`` (pending / in_progress /
finished / error), a short ``title`` and the full ``content`` body. The
task-board view is computed on the fly from these notes; there is no separate
state machine.

This mirrors the soft-structured artefact pattern (Claude Code style): the
whiteboard holds the *communication artefacts* an agent produces so OTHER
agents can consume them, instead of stuffing the whole result through the
conversation (the "game of telephone" problem). Soft-structured means
``kind`` is a free tag, NOT an enforced enum.
"""

from __future__ import annotations

import aiosqlite
import logging
import uuid
from typing import Any

from .db import _db_path

logger = logging.getLogger(__name__)


class WhiteboardStore:
    """Async CRUD for whiteboard notes, scoped per topic."""

    async def create(
        self,
        *,
        topic_id: str,
        author: str,
        kind: str = "task",
        status: str = "pending",
        title: str | None = None,
        content: str | None = None,
        note_id: str | None = None,
    ) -> dict[str, Any]:
        nid = note_id or uuid.uuid4().hex
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                """INSERT INTO whiteboard_note
                       (id, topic_id, author, kind, status, title, content)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (nid, topic_id, author, kind, status, title, content),
            )
            await db.commit()
        return await self.get(nid) or {"id": nid}

    async def get(self, note_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM whiteboard_note WHERE id = ?", (note_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_in_topic(
        self,
        topic_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """All notes in a topic, newest-first. Optionally filter by status."""
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            if status:
                cur = await db.execute(
                    "SELECT * FROM whiteboard_note "
                    "WHERE topic_id = ? AND status = ? "
                    "ORDER BY created_at DESC",
                    (topic_id, status),
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM whiteboard_note "
                    "WHERE topic_id = ? "
                    "ORDER BY created_at DESC",
                    (topic_id,),
                )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def update_status(
        self, note_id: str, status: str
    ) -> dict[str, Any] | None:
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                "UPDATE whiteboard_note SET status = ? WHERE id = ?",
                (status, note_id),
            )
            await db.commit()
        return await self.get(note_id)

    async def delete(self, note_id: str) -> bool:
        async with aiosqlite.connect(_db_path()) as db:
            cur = await db.execute(
                "DELETE FROM whiteboard_note WHERE id = ?", (note_id,)
            )
            await db.commit()
            return cur.rowcount > 0


# Module-level singleton.
whiteboard_store = WhiteboardStore()
