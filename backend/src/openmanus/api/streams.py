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
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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

    Does NOT stream the run — returns immediately. The client should open
    ``GET /stream?sessions=<session_id>`` to receive the agent's streamed
    output. Splitting trigger (POST) from delivery (GET) keeps both simple and
    reliable.
    """
    s = await session_store.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    agent = await _resolve_agent(request, s)
    # speaker = who PRODUCES the streamed text = this session's agent identity.
    speaker = s.get("name") or ("teamleader" if s.get("kind") == "team" else "assistant")

    # Run the agent in the BACKGROUND. It pushes events onto the session's
    # channel; the client drains them via GET /stream. We don't await the run
    # here — that's the whole point (POST returns fast).
    #
    # include_subgraphs: the DEFAULT entry agent is a pure router — its only
    # tool is `dispatch`, which launches sub-agents as INDEPENDENT background
    # tasks on their OWN channels. With subgraphs=True, the router's astream
    # would ALSO mirror those sub-agent chunks (tagged with the router's
    # session_id) → the router's stream gets contaminated with the coder's
    # file-tool output ("串台"). subgraphs=False keeps the router's stream to
    # just its own routing decision.
    is_router = s.get("kind") == "root"
    asyncio.create_task(
        engine._stream(
            agent=agent, session_id=session_id, prompt=body.content, speaker=speaker,
            include_subgraphs=not is_router,
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
