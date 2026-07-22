"""Channel registry: one live event queue per session + topic fan-in.

Replaces the old SingleRegistry + TeamRegistry (two near-duplicate
dict[id]->Queue). Now there is ONE registry: every agent participant gets a
channel (an ``asyncio.Queue``) the moment it's needed, and the SSE endpoint
drains it.

TOPIC FAN-IN (decision 1): "watch a topic" = subscribe to every participant
session's channel in that topic, then forward every frame verbatim in arrival
order. No cross-session reordering, no merging — each frame already carries
``session_id`` so the frontend splits it back into the right participant's
message list.

Also wires the live half of mailbox hybrid persistence: importing this module
registers a pusher with ``mailbox`` so a ``mailbox.send`` to a running agent
also drops a frame on that agent's channel (the agent reads it as a mailbox
message mid-turn).
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from . import mailbox as _mailbox
from .db import session_store
from .event_schema import done_sentinel, frame, is_done_sentinel

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """In-process registry of per-session live event queues."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        # session_ids known to have finished (so fan-in can tell "all done").
        self._finished: set[str] = set()

    def get_queue(self, session_id: str) -> asyncio.Queue:
        q = self._queues.get(session_id)
        if q is None:
            q = asyncio.Queue()
            self._queues[session_id] = q
        return q

    def has(self, session_id: str) -> bool:
        return session_id in self._queues

    def discard(self, session_id: str) -> None:
        self._queues.pop(session_id, None)
        self._finished.discard(session_id)

    def mark_finished(self, session_id: str) -> None:
        self._finished.add(session_id)

    def is_finished(self, session_id: str) -> bool:
        return session_id in self._finished

    async def _push_live(self, topic_id: str, to_agent: str, msg_dict: dict) -> None:
        """Push a mailbox message to all live channels of the recipient agent.

        Finds all sessions of (topic_id, to_agent) that have a live SSE listener
        and drops the mailbox frame onto their channels. This is the push half
        of hybrid mailbox persistence — the DB write is durable regardless, but
        this gives real-time delivery to connected frontends.
        """
        from .db import session_store as _ss
        try:
            members = await _ss.list_in_topic(topic_id)
        except Exception:  # noqa: BLE001
            return
        for s in members:
            if s.get("name") != to_agent:
                continue
            sid = s["id"]
            if not self.has(sid):
                continue
            enriched = dict(msg_dict)
            ev = {
                "kind": "mailbox",
                "session_id": sid,
                "mailbox": enriched,
            }
            await self.get_queue(sid).put(frame(ev))


# Module-level singleton.
channels = ChannelRegistry()

# Wire the live pusher into mailbox (hybrid persistence push half).
_mailbox.set_channel_pusher(channels._push_live)


async def drain_single(queue: asyncio.Queue) -> AsyncIterator[str]:
    """Yield SSE frames from one queue until its done sentinel, then ``[DONE]``."""
    while True:
        item = await queue.get()
        if is_done_sentinel(item):
            yield "data: [DONE]\n\n"
            return
        # items are already SSE-formatted strings ("data: {...}\n\n")
        yield item


async def drain_sessions(
    session_ids: list[str],
    *,
    stop_when_done: set[str] | None = None,
) -> AsyncIterator[str]:
    """Merge frames from several sessions' queues into one stream.

    Forwards every frame verbatim in arrival order (no reordering, no merging —
    each frame carries ``session_id`` so the client splits it back). Closes with
    ``[DONE]`` once every session id in ``stop_when_done`` has emitted its done
    sentinel. Sessions not in ``stop_when_done`` are drained opportunistically
    but don't gate termination (e.g. members that never start).

    If ``stop_when_done`` is empty/None, the stream runs until all given
    sessions are done.
    """
    gate = set(stop_when_done) if stop_when_done else set(session_ids)
    seen_done: set[str] = set()
    # Track which sessions still have a pending queue.get so we don't drop them.
    active = set(session_ids)

    while active:
        # Rebuild get-tasks for active sessions each iteration.
        tasks: dict[asyncio.Task, str] = {}
        for sid in list(active):
            tasks[asyncio.ensure_future(channels.get_queue(sid).get())] = sid
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            sid = tasks[t]
            item = t.result()
            if is_done_sentinel(item):
                seen_done.add(sid)
                continue
            yield item
        # cancel the gets that didn't resolve this round; we'll re-issue them
        for t in pending:
            t.cancel()
        # terminate once every gating session is done
        if gate and gate <= seen_done:
            break
        if not gate and active <= seen_done:
            break

    yield "data: [DONE]\n\n"


async def fan_in(
    topic_id: str | None,
    focus_session_id: str | None = None,
) -> AsyncIterator[str]:
    """Merge frames from a focus session (+ its topic siblings) into one stream.

    * ``topic_id is None`` and ``focus_session_id`` set → single-session view:
      just drain ``focus_session_id``.
    * ``topic_id`` set → topic view: drain every participant in that topic. The
      member list is **re-scanned periodically** so sub-agents spawned mid-stream
      (TeamLeader delegating Researcher/Coder) are picked up automatically
      without the client reconnecting.

    TERMINATION: if ``focus_session_id`` is provided, the stream ends when that
    session (the TeamLeader / orchestrator) signals done — when the orchestrator
    is finished, the topic's work is finished. If ``focus_session_id`` is None,
    the stream ends only when EVERY known member is done (used when the SSE
    endpoint only knows the topic, not a specific orchestrator session).
    """
    if topic_id is None and focus_session_id is not None:
        async for f in drain_single(channels.get_queue(focus_session_id)):
            yield f
        return

    if topic_id is None:
        # Nothing to drain (no topic, no focus). Just close.
        yield "data: [DONE]\n\n"
        return

    # Topic view: dynamically expand members as they're created.
    known: set[str] = set()
    if focus_session_id:
        known.add(focus_session_id)
    focus_done = False
    all_done = False

    while (focus_session_id and not focus_done) or (not focus_session_id and not all_done):
        # Re-scan topic membership each round so newly-spawned agents join.
        members = await session_store.list_in_topic(topic_id)
        known.update(s["id"] for s in members)

        # Drain one round of frames from all known sessions.
        tasks: dict[asyncio.Task, str] = {}
        for sid in known:
            tasks[asyncio.ensure_future(channels.get_queue(sid).get())] = sid
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            sid = tasks[t]
            item = t.result()
            if is_done_sentinel(item):
                if sid == focus_session_id:
                    focus_done = True
                continue
            yield item
        for t in pending:
            t.cancel()
        # No-focus mode: terminate once every known member is done.
        if not focus_session_id:
            seen_done = {sid for sid in known if channels.is_finished(sid)}
            if known and seen_done == known:
                all_done = True

    yield "data: [DONE]\n\n"
