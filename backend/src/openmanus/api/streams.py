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


@router.post("/sessions/{session_id}/messages")
async def post_message(
    session_id: str, body: PostMessage, request: Request
) -> dict:
    """Send a user message and TRIGGER the agent run (background, non-blocking).

    Special commands (processed before the agent runs):
      /cd <path>   — switch this session's workdir (sandbox root).
                     Affects all subsequent dispatch + file operations.
    """
    s = await session_store.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    content = body.content.strip()

    # ── /cd command: switch workdir ──────────────────────────────────────
    if content.startswith("/cd ") or content == "/cd":
        path = content[4:].strip() if len(content) > 3 else ""
        if not path:
            # /cd with no arg: show current workdir
            cur = s.get("workdir") or "(not set)"
            queue = channels.get_queue(session_id)
            await queue.put(E.frame(E.ev_message_start(
                session_id=session_id, message_id=f"cd-{uuid.uuid4().hex}",
                speaker="system",
            )))
            await queue.put(E.frame(E.ev_text_delta(
                session_id=session_id, message_id=f"cd-resp",
                speaker="system", delta=f"📁 Current workdir: {cur}",
            )))
            await queue.put(E.frame(E.ev_message_end(
                session_id=session_id, message_id=f"cd-resp",
                speaker="system",
            )))
            await queue.put(E.frame(E.ev_done(session_id=session_id)))
            await queue.put(E.done_sentinel(session_id))
            return {"ok": True, "session_id": session_id, "action": "pwd"}

        # expand + validate
        from pathlib import Path
        target = Path(path).expanduser().resolve()
        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=400, detail=f"path does not exist or not a directory: {target}")

        # update session workdir
        await session_store.update(session_id, workdir=str(target))

        # rebuild agent with new workdir (so the backend root_dir matches)
        from ..agent_factory import build_agent
        agent = await build_agent(s.get("name") or "Manus", str(target))

        # push a confirmation message to the stream
        queue = channels.get_queue(session_id)
        msg_id = f"cd-{uuid.uuid4().hex}"
        await queue.put(E.frame(E.ev_message_start(
            session_id=session_id, message_id=msg_id, speaker="system",
        )))
        await queue.put(E.frame(E.ev_text_delta(
            session_id=session_id, message_id=msg_id, speaker="system",
            delta=f"📁 Workdir switched to: {target}",
        )))
        await queue.put(E.frame(E.ev_message_end(
            session_id=session_id, message_id=msg_id, speaker="system",
        )))
        await queue.put(E.frame(E.ev_done(session_id=session_id)))
        await queue.put(E.done_sentinel(session_id))
        return {"ok": True, "session_id": session_id, "action": "cd", "workdir": str(target)}

    # ── normal message: run agent ────────────────────────────────────────
    workdir = s.get("workdir") or settings.workdir
    agent = await _resolve_agent(request, s)
    # rebuild agent with session's workdir (in case it was changed by /cd earlier)
    if s.get("workdir"):
        from ..agent_factory import build_agent
        agent = await build_agent(s.get("name") or "Manus", workdir)

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
