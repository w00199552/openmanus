"""Unified event schema for the SSE stream (replaces AG-UI + GROUP_MESSAGE).

Every event is a plain dict carrying ``session_id`` + ``message_id`` + ``speaker``
so a single fanned-in stream can route each frame to the right participant's
view. This is the one contract between backend runners and the frontend
reducer — there is no more AG-UI protocol layer and no custom GROUP_MESSAGE
frame; speaker-awareness is built into the base event.

Event kinds:
  message_start   {kind, session_id, message_id, speaker}
  text_delta      {kind, session_id, message_id, speaker, delta}
  message_end     {kind, session_id, message_id, speaker}
  tool_call_start {kind, session_id, message_id, speaker, call_id, tool}
  tool_call_args  {kind, session_id, call_id, args_json}
  tool_call_result{kind, session_id, call_id, result}
  tool_call_end   {kind, session_id, call_id}
  step_start      {kind, session_id, node}
  step_end        {kind, session_id, node}
  error           {kind, session_id, message}
  done            {kind, session_id}

Frames are SSE-encoded as ``data: {json}\\n\\n``. Streams close with the literal
``data: [DONE]\\n\\n`` after every participating session has emitted ``done``.
"""

from __future__ import annotations

import json
from typing import Any

# Sentinel pushed onto a channel to signal "this session finished". Distinct
# from the `done` EVENT (which is a rendered frame the client sees): the
# sentinel is internal, consumed by the channel drainer.
DONE_TYPE = "__done__"


def done_sentinel(session_id: str) -> dict[str, Any]:
    """Internal end-of-stream marker for a session's channel."""
    return {"type": DONE_TYPE, "session_id": session_id}


def is_done_sentinel(item: Any) -> bool:
    return isinstance(item, dict) and item.get("type") == DONE_TYPE


def frame(event: dict[str, Any]) -> str:
    """Render an event dict as an SSE frame: ``data: {...}\\n\\n``."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# --- event constructors ----------------------------------------------------
# Thin helpers so call sites read clearly and the `kind` strings stay in one
# place. Each carries session_id + (where relevant) message_id + speaker.


def ev_message_start(*, session_id: str, message_id: str, speaker: str) -> dict[str, Any]:
    return {"kind": "message_start", "session_id": session_id, "message_id": message_id, "speaker": speaker}


def ev_text_delta(*, session_id: str, message_id: str, speaker: str, delta: str) -> dict[str, Any]:
    return {"kind": "text_delta", "session_id": session_id, "message_id": message_id, "speaker": speaker, "delta": delta}


def ev_thinking_delta(*, session_id: str, message_id: str, speaker: str, delta: str) -> dict[str, Any]:
    """A chunk of the model's reasoning/thinking trace (separate from the answer).

    GLM exposes this as `reasoning_content` on its native OpenAI endpoint; we
    surface it as its own event so the frontend can render a collapsible
    "thinking" region above the answer, mirroring Claude/DeepSeek UX.
    """
    return {"kind": "thinking_delta", "session_id": session_id, "message_id": message_id, "speaker": speaker, "delta": delta}


def ev_message_end(*, session_id: str, message_id: str, speaker: str) -> dict[str, Any]:
    return {"kind": "message_end", "session_id": session_id, "message_id": message_id, "speaker": speaker}


def ev_tool_call_start(*, session_id: str, message_id: str, speaker: str, call_id: str, tool: str) -> dict[str, Any]:
    return {"kind": "tool_call_start", "session_id": session_id, "message_id": message_id, "speaker": speaker, "call_id": call_id, "tool": tool}


def ev_tool_call_args(*, session_id: str, call_id: str, args_json: str) -> dict[str, Any]:
    return {"kind": "tool_call_args", "session_id": session_id, "call_id": call_id, "args_json": args_json}


def ev_tool_call_result(*, session_id: str, call_id: str, result: str) -> dict[str, Any]:
    return {"kind": "tool_call_result", "session_id": session_id, "call_id": call_id, "result": result}


def ev_tool_call_end(*, session_id: str, call_id: str) -> dict[str, Any]:
    return {"kind": "tool_call_end", "session_id": session_id, "call_id": call_id}


def ev_step_start(*, session_id: str, node: str) -> dict[str, Any]:
    return {"kind": "step_start", "session_id": session_id, "node": node}


def ev_step_end(*, session_id: str, node: str) -> dict[str, Any]:
    return {"kind": "step_end", "session_id": session_id, "node": node}


def ev_error(*, session_id: str, message: str) -> dict[str, Any]:
    return {"kind": "error", "session_id": session_id, "message": message}


def ev_done(*, session_id: str) -> dict[str, Any]:
    return {"kind": "done", "session_id": session_id}
