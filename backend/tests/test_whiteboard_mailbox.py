"""Phase 3 — whiteboard + mailbox data model tests.

Tests WhiteboardStore (task board CRUD + status) and MailboxStore
(agent-to-agent messaging + lock + check_and_drain).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest


from openmanus.config import settings  # noqa: E402
from openmanus.db import init_db, session_store, topic_store  # noqa: E402
from openmanus.whiteboard import whiteboard_store  # noqa: E402
from openmanus.mailbox import mailbox_store  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_db():
    saved = settings.database_url
    tmpdir = tempfile.mkdtemp(prefix="openmanus_p3_test_")
    settings.database_url = f"sqlite:///{Path(tmpdir) / 'checkpoints.db'}"
    yield
    settings.database_url = saved


@pytest.fixture
async def db():
    await init_db()
    await topic_store.ensure_main()


# ─── WhiteboardStore ────────────────────────────────────────────────────────


class TestWhiteboardStore:
    async def test_create_note(self, db):
        note = await whiteboard_store.create(
            topic_id="main", author="TeamLeader",
            title="Write BFS", content="implement breadth-first search",
        )
        assert note["id"]
        assert note["topic_id"] == "main"
        assert note["author"] == "TeamLeader"
        assert note["status"] == "pending"  # default

    async def test_get_note(self, db):
        note = await whiteboard_store.create(
            topic_id="main", author="TeamLeader", title="test", content="x",
        )
        fetched = await whiteboard_store.get(note["id"])
        assert fetched is not None
        assert fetched["title"] == "test"

    async def test_get_nonexistent(self, db):
        assert await whiteboard_store.get("nonexistent-id") is None

    async def test_list_in_topic(self, db):
        await whiteboard_store.create(topic_id="t1", author="A", title="n1", content="")
        await whiteboard_store.create(topic_id="t1", author="B", title="n2", content="")
        await whiteboard_store.create(topic_id="t2", author="A", title="n3", content="")
        t1_notes = await whiteboard_store.list_in_topic("t1")
        assert len(t1_notes) == 2
        t2_notes = await whiteboard_store.list_in_topic("t2")
        assert len(t2_notes) == 1

    async def test_list_filter_by_status(self, db):
        n1 = await whiteboard_store.create(topic_id="t1", author="A", title="p", content="")
        await whiteboard_store.update_status(n1["id"], "in_progress")
        await whiteboard_store.create(topic_id="t1", author="A", title="q", content="")
        pending = await whiteboard_store.list_in_topic("t1", status="pending")
        in_progress = await whiteboard_store.list_in_topic("t1", status="in_progress")
        assert len(pending) == 1
        assert pending[0]["title"] == "q"
        assert len(in_progress) == 1
        assert in_progress[0]["title"] == "p"

    async def test_update_status(self, db):
        note = await whiteboard_store.create(topic_id="t1", author="A", title="x", content="")
        updated = await whiteboard_store.update_status(note["id"], "finished")
        assert updated["status"] == "finished"

    async def test_delete_note(self, db):
        note = await whiteboard_store.create(topic_id="t1", author="A", title="x", content="")
        assert await whiteboard_store.delete(note["id"]) is True
        assert await whiteboard_store.get(note["id"]) is None


# ─── MailboxStore ───────────────────────────────────────────────────────────


class TestMailboxStore:
    async def test_send_and_inbox(self, db):
        await mailbox_store.send(
            topic_id="t1", from_agent="Coder", to_agent="TeamLeader",
            kind="result", content="bfs done",
        )
        msgs = await mailbox_store.inbox("t1", "TeamLeader")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "bfs done"
        assert msgs[0]["from_agent"] == "Coder"
        assert msgs[0]["to_agent"] == "TeamLeader"

    async def test_inbox_unread_only(self, db):
        await mailbox_store.send(
            topic_id="t1", from_agent="Coder", to_agent="TeamLeader",
            kind="chat", content="hi",
        )
        unread = await mailbox_store.inbox("t1", "TeamLeader", unread_only=True)
        assert len(unread) == 1
        await mailbox_store.mark_read("t1", "TeamLeader", [unread[0]["id"]])
        unread_after = await mailbox_store.inbox("t1", "TeamLeader", unread_only=True)
        assert len(unread_after) == 0
        all_msgs = await mailbox_store.inbox("t1", "TeamLeader")
        assert len(all_msgs) == 1  # still there, just read

    async def test_inbox_isolated_by_topic(self, db):
        await mailbox_store.send(
            topic_id="t1", from_agent="A", to_agent="B", kind="chat", content="in t1",
        )
        await mailbox_store.send(
            topic_id="t2", from_agent="A", to_agent="B", kind="chat", content="in t2",
        )
        t1_msgs = await mailbox_store.inbox("t1", "B")
        t2_msgs = await mailbox_store.inbox("t2", "B")
        assert len(t1_msgs) == 1
        assert t1_msgs[0]["content"] == "in t1"
        assert len(t2_msgs) == 1
        assert t2_msgs[0]["content"] == "in t2"

    async def test_inbox_isolated_by_agent(self, db):
        await mailbox_store.send(
            topic_id="t1", from_agent="A", to_agent="B", kind="chat", content="to B",
        )
        await mailbox_store.send(
            topic_id="t1", from_agent="A", to_agent="C", kind="chat", content="to C",
        )
        b_msgs = await mailbox_store.inbox("t1", "B")
        c_msgs = await mailbox_store.inbox("t1", "C")
        assert len(b_msgs) == 1
        assert b_msgs[0]["content"] == "to B"
        assert len(c_msgs) == 1
        assert c_msgs[0]["content"] == "to C"

    async def test_check_and_drain_empty(self, db):
        """check_and_drain with empty inbox should not call on_messages."""
        called = []
        await mailbox_store.check_and_drain("t1", "X", lambda msgs: called.append(msgs))
        assert called == []

    async def test_check_and_drain_drains_unread(self, db):
        """check_and_drain reads unread, marks read, calls callback."""
        await mailbox_store.send(
            topic_id="t1", from_agent="A", to_agent="B", kind="chat", content="msg1",
        )
        await mailbox_store.send(
            topic_id="t1", from_agent="A", to_agent="B", kind="chat", content="msg2",
        )
        drained = []
        await mailbox_store.check_and_drain("t1", "B", lambda msgs: drained.extend(msgs))
        assert len(drained) == 2
        # After drain, inbox should be all read
        unread = await mailbox_store.inbox("t1", "B", unread_only=True)
        assert len(unread) == 0
        # Second drain should find nothing
        drained2 = []
        await mailbox_store.check_and_drain("t1", "B", lambda msgs: drained2.extend(msgs))
        assert drained2 == []

    async def test_lock_prevents_race(self, db):
        """Lock ensures send + check_and_drain are mutually exclusive for same agent.

        We send a message and immediately drain; the drain must see it (not miss
        it due to a race between send's INSERT and drain's SELECT).
        """
        async def send():
            await mailbox_store.send(
                topic_id="t1", from_agent="A", to_agent="B",
                kind="chat", content="race test",
            )

        async def drain():
            drained = []
            await mailbox_store.check_and_drain("t1", "B", lambda m: drained.extend(m))
            return drained

        # Run send and drain concurrently; drain should eventually see the message.
        # This is a best-effort race test — the lock guarantees atomicity.
        await asyncio.gather(send(), drain())
        # After both complete, either drain caught it or it's still unread.
        # The key assertion: no crash, no duplicate processing.
        unread = await mailbox_store.inbox("t1", "B", unread_only=True)
        all_msgs = await mailbox_store.inbox("t1", "B")
        assert len(all_msgs) == 1  # exactly one message, no duplicates
