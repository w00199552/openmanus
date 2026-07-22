"""Phase 1 — topic/session data model + thread_id computation.

Tests the new data layer: TopicStore CRUD, SessionStore with topic_id,
and the compute_thread_id function. Uses an isolated temp DB per test session
by monkeypatching settings.database_url (NOT env var — pydantic-settings
caches at init, so env changes after import don't take effect).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


from openmanus.db import (  # noqa: E402
    MAIN_TOPIC_ID,
    SessionStore,
    TopicStore,
    init_db,
    session_store,
    topic_store,
)
from openmanus.agent_factory import (  # noqa: E402
    _resolve_session_id,
    _resolve_topic_id,
    compute_thread_id,
)
from openmanus.config import settings  # noqa: E402


# ─── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolate_db():
    """Point settings.database_url at a FRESH temp DB for each test.

    A new tempdir per test avoids schema conflicts when the test suite's
    shared DB (./data/sessions.db) has an older schema.
    """
    saved = settings.database_url
    tmpdir = tempfile.mkdtemp(prefix="openmanus_test_")
    settings.database_url = f"sqlite:///{Path(tmpdir) / 'checkpoints.db'}"
    yield
    settings.database_url = saved


@pytest.fixture
async def db():
    """Fresh tables (init_db is idempotent — safe to call per test)."""
    await init_db()
    return topic_store


# ─── compute_thread_id ─────────────────────────────────────────────────────


class TestComputeThreadId:
    """thread_id = f"{topic_id}:{agent_name}" — the memory-chain key."""

    def test_basic(self):
        assert compute_thread_id("topic-abc", "Coder") == "topic-abc:Coder"

    def test_main_topic(self):
        assert compute_thread_id("main", "Manus") == "main:Manus"

    def test_same_agent_same_topic_shares_thread(self):
        """Two sessions of the same agent in the same topic → same thread."""
        t = compute_thread_id("topic-1", "Researcher")
        assert compute_thread_id("topic-1", "Researcher") == t

    def test_different_agents_isolate(self):
        """Different agents in the same topic → different threads."""
        assert compute_thread_id("topic-1", "Coder") != compute_thread_id("topic-1", "Researcher")

    def test_different_topics_isolate(self):
        """Same agent in different topics → different threads (full isolation)."""
        assert compute_thread_id("topic-1", "Coder") != compute_thread_id("topic-2", "Coder")


# ─── TopicStore ─────────────────────────────────────────────────────────────


class TestTopicStore:
    async def test_create_and_get(self, db):
        t = await db.create(title="bfs task", workdir="/tmp/bfs")
        assert t["id"].startswith("topic-")
        assert t["title"] == "bfs task"
        fetched = await db.get(t["id"])
        assert fetched is not None
        assert fetched["title"] == "bfs task"

    async def test_ensure_main_creates_if_absent(self, db):
        t = await db.ensure_main()
        assert t["id"] == MAIN_TOPIC_ID
        assert t["title"] == "Main"

    async def test_ensure_main_idempotent(self, db):
        t1 = await db.ensure_main()
        t2 = await db.ensure_main()
        assert t1["id"] == t2["id"] == MAIN_TOPIC_ID

    async def test_update_workdir(self, db):
        t = await db.create(title="test", workdir="/old")
        updated = await db.update_workdir(t["id"], "/new")
        assert updated["workdir"] == "/new"

    async def test_list(self, db):
        await db.create(title="task A")
        await db.create(title="task B")
        await db.ensure_main()
        topics = await db.list()
        assert len(topics) >= 3
        titles = [t["title"] for t in topics]
        assert "task A" in titles
        assert "task B" in titles
        assert "Main" in titles

    async def test_delete(self, db):
        t = await db.create(title="disposable")
        assert await db.delete(t["id"]) is True
        assert await db.get(t["id"]) is None

    async def test_cannot_delete_main(self, db):
        await db.ensure_main()
        assert await db.delete(MAIN_TOPIC_ID) is False
        assert await db.get(MAIN_TOPIC_ID) is not None


# ─── SessionStore ──────────────────────────────────────────────────────────


class TestSessionStore:
    async def test_create_requires_topic_id(self, db):
        """topic_id is now the first positional-ish param (keyword, required)."""
        main = await db.ensure_main()
        s = await session_store.create(topic_id=main["id"], name="Manus", kind="root")
        assert s["topic_id"] == main["id"]
        assert s["name"] == "Manus"

    async def test_create_generates_session_id(self, db):
        main = await db.ensure_main()
        s = await session_store.create(topic_id=main["id"], name="Coder")
        assert s["id"].startswith("sess-")

    async def test_create_with_explicit_session_id(self, db):
        main = await db.ensure_main()
        s = await session_store.create(
            topic_id=main["id"], name="Manus", session_id="custom-id"
        )
        assert s["id"] == "custom-id"

    async def test_get(self, db):
        main = await db.ensure_main()
        s = await session_store.create(topic_id=main["id"], name="Coder")
        fetched = await session_store.get(s["id"])
        assert fetched is not None
        assert fetched["name"] == "Coder"
        assert fetched["topic_id"] == main["id"]

    async def test_list_in_topic(self, db):
        topic_a = await db.create(title="topic A")
        topic_b = await db.create(title="topic B")
        await session_store.create(topic_id=topic_a["id"], name="Coder")
        await session_store.create(topic_id=topic_a["id"], name="Researcher")
        await session_store.create(topic_id=topic_b["id"], name="Coder")

        in_a = await session_store.list_in_topic(topic_a["id"])
        assert len(in_a) == 2
        in_b = await session_store.list_in_topic(topic_b["id"])
        assert len(in_b) == 1

    async def test_list_filter_by_kind(self, db):
        main = await db.ensure_main()
        await session_store.create(topic_id=main["id"], name="Coder", kind="subagent")
        await session_store.create(topic_id=main["id"], name="Manus", kind="root")
        roots = await session_store.list(kind="root")
        assert all(s["kind"] == "root" for s in roots)
        assert len(roots) >= 1

    async def test_update_status(self, db):
        main = await db.ensure_main()
        s = await session_store.create(topic_id=main["id"], name="Coder")
        updated = await session_store.update(s["id"], status="running")
        assert updated["status"] == "running"

    async def test_delete(self, db):
        main = await db.ensure_main()
        s = await session_store.create(topic_id=main["id"], name="Coder")
        assert await session_store.delete(s["id"]) is True
        assert await session_store.get(s["id"]) is None

    async def test_thread_id_from_session_row(self, db):
        """A session row has topic_id + name → thread_id is computable."""
        topic = await db.create(title="test thread")
        s = await session_store.create(topic_id=topic["id"], name="Coder")
        # build_agent reads these from the row and computes thread_id:
        tid = compute_thread_id(s["topic_id"], s["name"])
        assert tid == f"{topic['id']}:Coder"


# ─── _resolve_* config helpers ──────────────────────────────────────────────


class TestResolveConfig:
    """Phase 1: tools read session_id/topic_id from config, not thread_id."""

    def test_resolve_session_id(self):
        config = {"configurable": {"session_id": "sess-123", "thread_id": "main:Manus"}}
        assert _resolve_session_id(config) == "sess-123"

    def test_resolve_session_id_missing(self):
        assert _resolve_session_id({}) == "unknown"
        assert _resolve_session_id(None) == "unknown"

    def test_resolve_topic_id(self):
        config = {"configurable": {"topic_id": "topic-abc"}}
        assert _resolve_topic_id(config) == "topic-abc"

    def test_resolve_topic_id_missing(self):
        assert _resolve_topic_id({}) is None
        assert _resolve_topic_id(None) is None

    def test_resolve_does_not_use_thread_id(self):
        """Regression guard: session_id must NOT come from thread_id anymore."""
        config = {"configurable": {"thread_id": "main:Manus"}}
        # thread_id is set but session_id is not → should return unknown,
        # NOT the thread_id value.
        assert _resolve_session_id(config) == "unknown"
