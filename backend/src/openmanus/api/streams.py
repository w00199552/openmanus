"""Unified SSE stream endpoints.

Standard Server-Sent Events via ``sse-starlette``'s ``EventSourceResponse``.

Two responsibilities, cleanly separated:

* ``POST /sessions/{session_id}/messages`` — user → agent: send a message and
  TRIGGER the agent run in the background. Returns immediately with ``{"ok":
  true, "session_id": ...}`` — it does NOT stream the run. The caller then opens
  a GET stream to receive the output (see below). This separation is what makes
  streaming reliable: the POST is a plain JSON request (no streaming-response
  lifecycle issues), and the GET is a pure SSE subscription.

* ``GET /stream`` — subscribe to a live event stream. Two query modes:
    - ``?scope=<team_id>``     → fan-in the whole team (the scope session + all
                                its members, dynamically expanded as new
                                sub-agents are spawned mid-run).
    - ``?sessions=id1,id2,...` → explicit set of sessions to merge.
  Every event carries ``session_id`` + ``speaker`` so a fanned-in stream is
  self-attributing: the client splits frames back into per-participant views.

Events are produced by ``runner.SessionRunner`` into per-session channels
(``channels.ChannelRegistry``); these endpoints just drain them as SSE.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any

from .. import event_schema as E
from ..channels import channels, drain_single, drain_sessions, fan_in
from ..config import settings
from ..db import session_store
from ..engine import engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["streams"])


class PostMessage(BaseModel):
    content: str


async def _resolve_agent(request: Request, session: dict[str, Any]) -> Any:
    """Pick the agent for this session.

    The entry agent (manus) is the cached app default. Dispatched agents are
    built fresh by the dispatch tool (not via this path — they run inside the
    dispatch tool's engine.start call). So for user-initiated messages we
    always use the entry agent.
    """
    return request.app.state.agent


class CdBody(BaseModel):
    path: str = ""


@router.post("/sessions/{session_id}/cd")
async def cd_session(session_id: str, body: CdBody) -> dict:
    """Switch a session's workdir. Does NOT trigger the agent — just updates
    the sandbox root + rebuilds the agent with the new backend root_dir.

    Behaves like a shell ``cd``:
      ``cd <subdir>``  — relative to current workdir
      ``cd ..``        — go up one level (stays at drive root if already there)
      ``cd D:\\path``  — absolute path
      ``cd``           — print current workdir (pwd)
    """
    s = await session_store.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    from pathlib import Path

    cur = Path(s.get("workdir") or settings.workdir)
    path = body.path.strip()

    # cd with no args → print current workdir
    if not path:
        return {"ok": True, "workdir": str(cur), "action": "pwd"}

    # Resolve: absolute stays absolute; relative joins current workdir
    raw = Path(path).expanduser()
    target = raw if raw.is_absolute() else cur / raw

    # resolve() collapses ".." naturally; at a Windows drive root (D:\),
    # going up keeps you at D:\ — exactly like cmd.
    try:
        target = target.resolve()
    except (OSError, RuntimeError):
        target = target.absolute()

    if not target.exists() or not target.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"path does not exist or not a directory: {path}",
        )

    # update session + global workdir.
    # NOTE: we don't rebuild the agent here — post_message reads the session's
    # workdir and rebuilds on the next message. This just updates the stored
    # value so the next message picks it up.
    await session_store.update(session_id, workdir=str(target))
    settings.workdir = str(target)

    return {"ok": True, "workdir": str(target), "action": "cd"}


@router.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: str, body: PostMessage, request: Request
) -> dict:
    """Send a user message and TRIGGER the agent run (background, non-blocking).
    """
    s = await session_store.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    content = body.content.strip()
    lower = content.lower()

    # ── skill command (case-insensitive, optional /) ───────────────────
    if lower.startswith("skill ") or lower == "skill" or lower.startswith("/skill ") or lower == "/skill":
        stripped = content.lstrip("/")
        skill_name = stripped[5:].strip()  # everything after "skill"

        # /skill with no arg: list available skills
        if not skill_name:
            from ..skill_loader import skill_loader
            queue = channels.get_queue(session_id)
            msg_id = f"skill-{uuid.uuid4().hex}"
            names = skill_loader.all_names()
            text = "📋 Available skills:\n" + ("\n".join(f"  skill {n}" for n in names) if names else "(no skills installed)")
            await queue.put(E.frame(E.ev_message_start(session_id=session_id, message_id=msg_id, speaker="system")))
            await queue.put(E.frame(E.ev_text_delta(session_id=session_id, message_id=msg_id, speaker="system", delta=text)))
            await queue.put(E.frame(E.ev_message_end(session_id=session_id, message_id=msg_id, speaker="system")))
            await queue.put(E.frame(E.ev_done(session_id=session_id)))
            await queue.put(E.done_sentinel(session_id))
            return {"ok": True, "session_id": session_id, "action": "skill-list"}

        # load the skill's SKILL.md
        from ..skill_loader import skill_loader
        sdir = skill_loader.skill_dir(skill_name)
        if not sdir or not sdir.exists():
            queue = channels.get_queue(session_id)
            msg_id = f"skill-{uuid.uuid4().hex}"
            await queue.put(E.frame(E.ev_message_start(session_id=session_id, message_id=msg_id, speaker="system")))
            await queue.put(E.frame(E.ev_text_delta(session_id=session_id, message_id=msg_id, speaker="system", delta=f"❌ Skill '{skill_name}' not found. Use /skill to list available.")))
            await queue.put(E.frame(E.ev_message_end(session_id=session_id, message_id=msg_id, speaker="system")))
            await queue.put(E.frame(E.ev_done(session_id=session_id)))
            await queue.put(E.done_sentinel(session_id))
            return {"ok": True, "session_id": session_id, "action": "skill-notfound"}

        skill_md = (sdir / "SKILL.md").read_text(encoding="utf-8")
        # rewrite content: inject the skill as context + keep any user text after it
        user_text = ""  # /skill alone = just activate the skill
        body.content = f"The user activated the skill '{skill_name}'. Follow its instructions for this and subsequent messages until told otherwise.\n\n--- Skill: {skill_name} ---\n{skill_md}\n--- End Skill ---\n\n{user_text}"

    # ── normal message: run agent ────────────────────────────────────────
    workdir = s.get("workdir") or settings.workdir
    # Use cached entry agent (rebuilds only when workdir changes).
    # TeamLeader sessions also use build_entry_agent with their own workdir.
    from ..agent_factory import build_entry_agent
    agent = await build_entry_agent(workdir)
    request.app.state.agent = agent

    speaker = s.get("name") or ("TeamLeader" if s.get("kind") == "team" else "Manus")

    asyncio.create_task(
        engine._stream(
            agent=agent, session_id=session_id, prompt=body.content, speaker=speaker,
        )
    )
    return {"ok": True, "session_id": session_id}


async def _sse_byte_stream(
    scope: str | None, sessions: list[str] | None
) -> Any:
    """Yield already-framed SSE byte strings (``data: {...}\\n\\n``).

    The channel layer (drain_single / fan_in / drain_sessions) produces
    fully-formatted SSE frames. We forward them verbatim — no re-framing, no
    re-buffering. This is what makes streaming token-by-token: we tried
    sse-starlette's EventSourceResponse first, but it batches output; yielding
    the raw frames through a plain StreamingResponse flushes each one as it
    arrives.
    """
    if scope:
        async for raw in fan_in(scope, scope):
            yield raw
        return
    if sessions:
        async for raw in drain_sessions(sessions):
            yield raw
        return
    yield "data: [DONE]\n\n"


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable nginx/proxy buffering
}


@router.get("/stream")
async def stream(
    scope: str | None = Query(default=None),
    sessions: str | None = Query(default=None),
) -> StreamingResponse:
    """Live SSE event stream.

    Pick ONE mode (mutually exclusive; scope wins if both given):
    - ``?scope=<team_id>``    → team fan-in (dynamically expands members).
    - ``?sessions=id1,id2``   → explicit session set.
    """
    sess_list = [s.strip() for s in sessions.split(",")] if sessions else None
    return StreamingResponse(
        _sse_byte_stream(scope, sess_list),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


class HealthResponse(BaseModel):
    status: str
    model: str
    workdir: str


@router.get("/health")
async def health() -> HealthResponse:
    from ..config import settings

    return HealthResponse(status="ok", model=settings.model, workdir=settings.workdir)
