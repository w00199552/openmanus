"""Checkpointer factory.

Conversation history is persisted by a LangGraph checkpointer keyed on the
AG-UI ``thread_id``. We pick SQLite by default (zero-dependency, a single
file) and switch to Postgres when the configured ``database_url`` points at
one, so a single setting moves the project from local dev to a real backend.

The savers need live async connections, so the factory is async and must be
called from within the event loop (the app lifespan does this).
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from pathlib import Path
from urllib.parse import urlparse


def _is_postgres(url: str) -> bool:
    scheme = urlparse(url).scheme.lower()
    return scheme.startswith(("postgres", "postgresql"))


def _sqlite_path(url: str) -> str:
    """Normalise a sqlite URL to a bare filesystem path + ensure dir exists."""
    path = url
    for prefix in ("sqlite:///", "sqlite://"):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    parent = Path(path).expanduser().parent
    parent.mkdir(parents=True, exist_ok=True)
    return path


async def get_checkpointer() -> BaseCheckpointSaver:
    url = settings.database_url

    if _is_postgres(url):
        # Postgres async saver. Connection string may arrive in either the
        # sqlalchemy ("postgresql+psycopg://") or libpq form.
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        conn = url.replace("postgresql+psycopg://", "postgresql://")
        saver = AsyncPostgresSaver.from_conn_string(conn)
        await saver.setup()
        return saver

    # Default: SQLite. AsyncSqliteSaver needs an open aiosqlite connection.
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    conn = await aiosqlite.connect(_sqlite_path(url))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver


# Late import to avoid a config-load cycle when this module is imported.
from .config import settings  # noqa: E402
