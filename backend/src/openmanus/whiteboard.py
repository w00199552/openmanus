"""Whiteboard: the inter-agent artefact space (the "communication" layer).

Distinct from the sandbox (the real filesystem where agents do their work):
the whiteboard holds the *communication artefacts* — structured results an
agent produces so OTHER agents can consume them. Per the unified model this is
the single source of truth for async results: a sub-agent writes its outcome
to the whiteboard, then sends the parent a short "done" mailbox message
carrying just the whiteboard reference (not the content — no double storage).

SOFT-STRUCTURED (decision: not a hard schema): each artefact has free-form
``content`` (text or JSON) plus light metadata — ``kind`` is a free tag the
agent chooses (research / plan / diff-summary / …), NOT an enforced enum.
The task-board view aggregates these on the fly from session status + kind; it
is not a stored state machine. This mirrors how Claude Code's filesystem-
artefact pattern stays flexible while avoiding the "game of telephone".
"""

from __future__ import annotations

import aiosqlite
import logging
import uuid
from typing import Any

from .db import _db_path

logger = logging.getLogger(__name__)


class WhiteboardStore:
    """Async CRUD for whiteboard artefacts, scoped per team-space."""

    async def create(
        self,
        *,
        scope_id: str,
        session_id: str,
        kind: str | None = None,
        title: str | None = None,
        content: str | None = None,
        artefact_id: str | None = None,
    ) -> dict[str, Any]:
        aid = artefact_id or f"art-{uuid.uuid4().hex}"
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                """INSERT INTO whiteboard (id, scope_id, session_id, kind, title, content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (aid, scope_id, session_id, kind, title, content),
            )
            await db.commit()
        return await self.get(aid) or {"id": aid}

    async def get(self, artefact_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM whiteboard WHERE id = ?", (artefact_id,)
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def list_in_scope(
        self, scope_id: str, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """All artefacts in a team-space, newest-first. Optionally filter by kind."""
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            if kind:
                cur = await db.execute(
                    "SELECT * FROM whiteboard WHERE scope_id = ? AND kind = ? "
                    "ORDER BY created_at DESC",
                    (scope_id, kind),
                )
            else:
                cur = await db.execute(
                    "SELECT * FROM whiteboard WHERE scope_id = ? "
                    "ORDER BY created_at DESC",
                    (scope_id,),
                )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def list_by_author(self, session_id: str) -> list[dict[str, Any]]:
        """All artefacts produced BY a given participant."""
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM whiteboard WHERE session_id = ? "
                "ORDER BY created_at DESC",
                (session_id,),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def update(
        self,
        artefact_id: str,
        *,
        content: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any] | None:
        sets: list[str] = []
        params: list[Any] = []
        if content is not None:
            sets.append("content = ?")
            params.append(content)
        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if not sets:
            return await self.get(artefact_id)
        params.append(artefact_id)
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                f"UPDATE whiteboard SET {', '.join(sets)} WHERE id = ?", params
            )
            await db.commit()
        return await self.get(artefact_id)

    async def delete(self, artefact_id: str) -> bool:
        async with aiosqlite.connect(_db_path()) as db:
            cur = await db.execute(
                "DELETE FROM whiteboard WHERE id = ?", (artefact_id,)
            )
            await db.commit()
            return cur.rowcount > 0


# Module-level singleton.
whiteboard_store = WhiteboardStore()
