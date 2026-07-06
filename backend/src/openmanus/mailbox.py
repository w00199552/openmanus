"""Mailbox: agent-to-agent messaging with hybrid persistence.

Each session (agent participant) has a mailbox — its inbox. Agents communicate
by sending messages to each other's mailboxes. This is the literal
"multi-person chat" substrate:

* ``dispatch`` — a task delegation ("@coder please implement X")
* ``result``   — a completed task's outcome ("done, see whiteboard #abc")
* ``chat``     — free-form inter-agent talk

HYBRID PERSISTENCE (decision 3-C): every message is BOTH written to the
``mailboxes`` table (durable history — survives restarts, powers task-board
reconstruction) AND pushed onto the recipient's live ``asyncio.Queue`` channel
(drives a running agent / live SSE fan-in). Two paths, one source of truth:
history replay reads the DB; live streaming drains the queue.

The live-push half is decoupled from this module via an injected pusher hook
(``set_channel_pusher``) to avoid a hard import cycle with ``channels`` /
``runner``. ``channels`` registers its pusher at import time; until then sends
are DB-only (still correct, just not real-time — which only matters for an
agent that's actively running, and runners always wire the pusher first).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

import aiosqlite

from .db import _db_path  # reuse the shared db-path helper

logger = logging.getLogger(__name__)

# Hook injected by ``channels`` so a send also pushes onto the recipient's live
# queue. Signature: async pusher(session_id, msg_dict) -> None. None = no live
# listener wired yet (DB-only send, still correct).
_channel_pusher: Callable[[str, dict], Awaitable[None]] | None = None

# Hook injected by ``engine`` so a send can WAKE UP an idle recipient.
# Signature: async wakeup(to_session_id, from_session_id) -> None.
# The engine checks the recipient's status: if IDLE, it starts a new turn with
# the message as prompt. If ACTIVE (running), the message just queues in the DB
# and the agent picks it up when its current turn ends.
_wakeup_handler: Callable[[str, str], Awaitable[None]] | None = None


def set_channel_pusher(pusher: Callable[[str, dict], Awaitable[None]]) -> None:
    """Register the live-queue pusher (called once by ``channels`` at import)."""
    global _channel_pusher
    _channel_pusher = pusher


def set_wakeup_handler(handler: Callable[[str, str], Awaitable[None]]) -> None:
    """Register the wake-up handler (called once by ``engine`` at import)."""
    global _wakeup_handler
    _wakeup_handler = handler


# Valid message kinds. Free-form beyond this — `content` carries the payload.
KIND_DISPATCH = "dispatch"
KIND_RESULT = "result"
KIND_CHAT = "chat"
_VALID_KINDS = {KIND_DISPATCH, KIND_RESULT, KIND_CHAT}


class MailboxStore:
    """Async CRUD for agent mailboxes (the inter-agent chat log)."""

    async def send(
        self,
        *,
        to_session_id: str,
        from_session_id: str,
        kind: str,
        content: str | None = None,
        whiteboard_ref: str | None = None,
    ) -> dict[str, Any]:
        """Deliver a message: persist to DB + push to recipient's live channel.

        Returns the stored message dict (with id + created_at). The push is
        fire-and-forget-safe: if no live listener is attached the message is
        still durably stored and will show up in ``inbox``.
        """
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"invalid mailbox kind {kind!r}; expected one of {_VALID_KINDS}"
            )

        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """INSERT INTO mailboxes
                   (session_id, from_session_id, kind, content, whiteboard_ref)
                   VALUES (?, ?, ?, ?, ?)""",
                (to_session_id, from_session_id, kind, content, whiteboard_ref),
            )
            msg_id = cur.lastrowid
            await db.commit()
            cur = await db.execute(
                "SELECT * FROM mailboxes WHERE id = ?", (msg_id,)
            )
            row = await cur.fetchone()

        msg = _row_to_mailbox(row)
        # Live half of hybrid persistence: notify any running listener.
        if _channel_pusher is not None:
            try:
                await _channel_pusher(to_session_id, msg)
            except Exception:  # noqa: BLE001 - never let a push failure drop the send
                logger.exception("mailbox live-push failed for %s", to_session_id)
        # Wake up the recipient if it's idle (not running). This is the
        # message-driven activation: the recipient starts a new turn with the
        # message as input. If the recipient is ACTIVE (running), the message
        # just queues in the DB and the agent picks it up when its turn ends.
        if _wakeup_handler is not None:
            try:
                await _wakeup_handler(to_session_id, from_session_id)
            except Exception:  # noqa: BLE001
                logger.exception("mailbox wake-up failed for %s", to_session_id)
        return msg

    async def inbox(
        self, session_id: str, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        """A participant's inbox, oldest-first. Powers history replay + task board."""
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            where = "WHERE session_id = ?"
            if unread_only:
                where += " AND read = 0"
            cur = await db.execute(
                f"SELECT * FROM mailboxes {where} ORDER BY created_at ASC, id ASC",
                (session_id,),
            )
            rows = await cur.fetchall()
            return [_row_to_mailbox(r) for r in rows]

    async def outbox(self, session_id: str) -> list[dict[str, Any]]:
        """Messages sent BY this participant (for audit / collaboration graphs)."""
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM mailboxes WHERE from_session_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (session_id,),
            )
            rows = await cur.fetchall()
            return [_row_to_mailbox(r) for r in rows]

    async def mark_read(self, session_id: str, msg_ids: list[int]) -> None:
        if not msg_ids:
            return
        placeholders = ",".join("?" * len(msg_ids))
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                f"UPDATE mailboxes SET read = 1 WHERE session_id = ? AND id IN ({placeholders})",
                (session_id, *msg_ids),
            )
            await db.commit()


def _row_to_mailbox(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    # `read` is stored as INTEGER 0/1; normalise to bool for callers.
    if "read" in d:
        d["read"] = bool(d["read"])
    return d


# Module-level singleton.
mailbox_store = MailboxStore()
