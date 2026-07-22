"""Mailbox: topic-scoped agent-to-agent messaging.

Agents in the same topic exchange messages through a shared ``mailboxes``
table. Messages are addressed by **agent name** (not session id) — every
delivery is topic-scoped: ``(topic_id, to_agent)`` identifies a recipient's
inbox. This is the literal "multi-person chat" substrate:

* ``dispatch`` — a task delegation ("@coder please implement X")
* ``result``   — a completed task's outcome ("done, see whiteboard #abc")
* ``chat``     — free-form inter-agent talk

Two concurrency invariants are enforced with a per-recipient ``asyncio.Lock``
(keyed by ``f"{topic_id}:{agent_name}"``):

* ``send`` atomically inserts a message AND fires the wake-up callback — so
  the engine never observes "message delivered but no wake-up" (or the
  reverse).
* ``check_and_drain`` atomically reads unread messages AND marks them read —
  so the engine's end-of-turn drain never races with a concurrent send.

Lock granularity is ``(topic_id, agent_name)``: a recipient's send side and
drain side are mutually exclusive, while unrelated agents run in parallel.

The live SSE push half is decoupled via an injected pusher hook
(``set_channel_pusher``) to avoid a hard import cycle with ``channels``.
``channels`` registers its pusher at import time; until then sends are
DB-only (still correct, just not real-time — which only matters for an agent
that's actively running, and runners always wire the pusher first).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import aiosqlite

from .db import _db_path  # reuse the shared db-path helper

logger = logging.getLogger(__name__)

# Hook injected by ``channels`` so a send also pushes onto the recipient's
# live SSE channel. Signature: async pusher(topic_id, to_agent, msg_dict).
# None = no live listener wired yet (DB-only send, still correct).
_channel_pusher: Callable[[str, str, dict], Awaitable[None]] | None = None

# Hook injected by ``engine`` so a send can WAKE UP an idle recipient.
# Signature: async callback(topic_id, agent_name) -> None.
# The engine checks the recipient's status: if IDLE, it starts a new session
# with the message as prompt. If ACTIVE (running), the message just queues in
# the DB and the agent picks it up via ``check_and_drain`` at end of turn.
_wakeup_callback: Callable[[str, str], Awaitable[None]] | None = None


def set_channel_pusher(pusher: Callable[[str, str, dict], Awaitable[None]]) -> None:
    """Register the live-queue pusher (called once by ``channels`` at import)."""
    global _channel_pusher
    _channel_pusher = pusher


def set_wakeup_callback(cb: Callable[[str, str], Awaitable[None]]) -> None:
    """Register the wake-up callback (called once by ``engine`` at import)."""
    global _wakeup_callback
    _wakeup_callback = cb


# Valid message kinds. Free-form beyond this — `content` carries the payload.
KIND_DISPATCH = "dispatch"
KIND_RESULT = "result"
KIND_CHAT = "chat"
_VALID_KINDS = {KIND_DISPATCH, KIND_RESULT, KIND_CHAT}


class MailboxStore:
    """Topic-scoped agent-to-agent messaging with per-recipient locking."""

    def __init__(self) -> None:
        # One lock per (topic_id, agent_name) — lazily created, reused.
        # Keyed by f"{topic_id}:{agent_name}".
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, topic_id: str, agent_name: str) -> asyncio.Lock:
        """Return the lock for (topic_id, agent_name), creating it on first use.

        Reused across calls so the same recipient's send and drain serialise
        against each other.
        """
        key = f"{topic_id}:{agent_name}"
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def send(
        self,
        *,
        topic_id: str,
        from_agent: str,
        to_agent: str,
        kind: str,
        content: str | None = None,
        whiteboard_ref: str | None = None,
    ) -> dict[str, Any]:
        """Deliver a message: persist to DB + push live + wake up recipient.

        The INSERT, the live push, and the wake-up decision all happen under
        the recipient's lock so they are atomic w.r.t. a concurrent
        ``check_and_drain`` on the same recipient — eliminating the
        stranded-message race (send arrives between an empty-inbox scan and
        session end, with no wake-up).

        Returns the stored message dict (with id + created_at). The push and
        wake-up are best-effort: failures are logged but never drop the send.
        """
        if kind not in _VALID_KINDS:
            raise ValueError(
                f"invalid mailbox kind {kind!r}; expected one of {_VALID_KINDS}"
            )

        lock = self._get_lock(topic_id, to_agent)
        async with lock:
            async with aiosqlite.connect(_db_path()) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    """INSERT INTO mailboxes
                       (topic_id, from_agent, to_agent, kind, content, whiteboard_ref)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (topic_id, from_agent, to_agent, kind, content, whiteboard_ref),
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
                    await _channel_pusher(topic_id, to_agent, msg)
                except Exception:  # noqa: BLE001 - never let a push failure drop the send
                    logger.exception(
                        "mailbox live-push failed for %s/%s", topic_id, to_agent
                    )
            # Wake up the recipient if idle. The engine decides what "idle"
            # means and starts a new session if so. Holding the recipient's
            # lock here makes this atomic against a concurrent check_and_drain.
            if _wakeup_callback is not None:
                try:
                    await _wakeup_callback(topic_id, to_agent)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "mailbox wake-up failed for %s/%s", topic_id, to_agent
                    )
        return msg

    async def inbox(
        self, topic_id: str, agent_name: str, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        """An agent's inbox in a topic, oldest-first.

        Powers history replay, the ``read_mailbox`` tool, and the task board.
        Does NOT take the lock — reads are pure SELECTs and tolerate
        concurrent sends (sqlite serialises writes; an unread row that
        appears mid-scan simply shows up next time, which is fine).
        """
        async with aiosqlite.connect(_db_path()) as db:
            db.row_factory = aiosqlite.Row
            where = "WHERE topic_id = ? AND to_agent = ?"
            if unread_only:
                where += " AND read = 0"
            cur = await db.execute(
                f"SELECT * FROM mailboxes {where} ORDER BY created_at ASC, id ASC",
                (topic_id, agent_name),
            )
            rows = await cur.fetchall()
            return [_row_to_mailbox(r) for r in rows]

    async def mark_read(
        self, topic_id: str, agent_name: str, msg_ids: list[int]
    ) -> None:
        """Mark the given message ids as read for this (topic, agent)."""
        if not msg_ids:
            return
        placeholders = ",".join("?" * len(msg_ids))
        async with aiosqlite.connect(_db_path()) as db:
            await db.execute(
                f"UPDATE mailboxes SET read = 1 "
                f"WHERE topic_id = ? AND to_agent = ? AND id IN ({placeholders})",
                (topic_id, agent_name, *msg_ids),
            )
            await db.commit()

    async def check_and_drain(
        self,
        topic_id: str,
        agent_name: str,
        on_messages: Callable[[list[dict[str, Any]]], Awaitable[None]],
    ) -> None:
        """End-of-turn drain. Atomically (under the recipient's lock):

        1. Read this agent's unread messages in the topic.
        2. If any: mark them read AND invoke ``on_messages(msgs)`` — the engine
           uses this callback to start a fresh turn with the messages as input.
        3. If none: do nothing (the agent stays idle).

        The lock makes "read unread + mark read" atomic w.r.t. a concurrent
        ``send`` to the same recipient, eliminating the stranded-message race
        (send-arrives-between-empty-inbox-scan-and-session-end).
        """
        lock = self._get_lock(topic_id, agent_name)
        async with lock:
            msgs = await self.inbox(topic_id, agent_name, unread_only=True)
            if not msgs:
                return
            await self.mark_read(topic_id, agent_name, [m["id"] for m in msgs])
            try:
                await on_messages(msgs)
            except Exception:  # noqa: BLE001 - don't let a callback error break the drain
                logger.exception(
                    "mailbox drain on_messages failed for %s/%s",
                    topic_id,
                    agent_name,
                )


def _row_to_mailbox(row: aiosqlite.Row) -> dict[str, Any]:
    d = dict(row)
    # `read` is stored as INTEGER 0/1; normalise to bool for callers.
    if "read" in d:
        d["read"] = bool(d["read"])
    return d


# Module-level singleton.
mailbox_store = MailboxStore()
