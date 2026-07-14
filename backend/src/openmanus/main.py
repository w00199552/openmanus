"""FastAPI application entrypoint.

Mounts the AG-UI run endpoint (POST /agents/main, a self-parsed SSE stream),
the sessions API, and CORS. Run with:

    uv run uvicorn openmanus.main:app --reload --port 8999
"""

from __future__ import annotations

# ── Windows UTF-8 fix ─────────────────────────────────────────────────────
# deepagents' LocalShellBackend runs shell commands via subprocess(text=True),
# which decodes output using the locale encoding. On a Chinese Windows that's
# cp936/GBK, so UTF-8 command output raises UnicodeDecodeError mid-agent-run.
# Force UTF-8 for child-process IO before anything spawns a subprocess.
# (PYTHONUTF8=1 enables Python's UTF-8 mode for the current and child procs.)
import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
import sys

if hasattr(sys, "reconfigure"):  # reconfigure std streams too (Py3.7+)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent_factory import build_entry_agent
from .agent_loader import agent_loader
from .api import agents, files, sessions, skills, streams, tools
from .api.sessions import workdir_router
from .config import settings
from .db import init_db, session_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("openmanus")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load agent definitions from ~/.openmanus/agents/ (seed builtins first run).
    agent_loader.seed_builtin()
    agent_loader.load_all()
    logger.info("loaded %d agents from %s", len(agent_loader.configs), agent_loader.dir)

    # Load user-defined tools from ~/.openmanus/tools/ (if exists).
    from .tool_loader import tool_loader
    tool_loader.load_all()
    if tool_loader.all_names():
        logger.info("loaded %d user tools from %s: %s",
                     len(tool_loader.all_names()), tool_loader.dir, tool_loader.all_names())

    # Load skills from ~/.openmanus/skills/ (if exists).
    from .skill_loader import skill_loader
    skill_loader.load_all()
    if skill_loader.all_names():
        logger.info("loaded %d skills from %s: %s",
                     len(skill_loader.all_names()), skill_loader.dir, skill_loader.all_names())

    await init_db()
    # Seed the singleton Manus entry session (idempotent; migrates legacy "default").
    manus_session = await session_store.ensure_manus()
    # Restore workdir from last session (so Sandbox shows the right dir on startup)
    if manus_session and manus_session.get("workdir"):
        settings.workdir = manus_session["workdir"]
    # Build the entry agent (manus) eagerly so the first request is fast.
    app.state.agent = await build_entry_agent()
    logger.info(
        "openmanus ready | model=%s base=%s workdir=%s db=%s",
        settings.model, settings.openai_base_url, settings.workdir, settings.database_url,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="openmanus", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Unified stream endpoints: POST /sessions/:id/messages, GET /sessions/:id/stream,
    # GET /scopes/:id/stream, GET /health.
    app.include_router(streams.router)
    app.include_router(sessions.router)
    app.include_router(agents.router)
    app.include_router(skills.router)
    app.include_router(tools.router)
    app.include_router(files.router)
    app.include_router(workdir_router)
    return app


app = create_app()
