"""Sessions REST API.

CRUD for sessions (the agent-conversation nodes). The history-flattening in
``get_session`` reads the checkpointer and returns an assistant-ui-compatible
message shape so the frontend can drop it straight into a Thread. Live streaming
lives in ``streams.py`` (POST /sessions/:id/messages, GET /sessions/:id/stream).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import session_store

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSession(BaseModel):
    kind: str = "root"
    name: str | None = None
    title: str | None = None
    workdir: str | None = None
    scope_id: str | None = None
    metadata: dict[str, Any] = {}


class UpdateSession(BaseModel):
    title: str | None = None
    status: str | None = None
    workdir: str | None = None
    metadata: dict[str, Any] | None = None


class SessionSummary(BaseModel):
    id: str
    kind: str
    name: str | None = None
    status: str
    title: str | None = None
    model: str | None = None
    workdir: str | None = None
    scope_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.post("", response_model=dict, status_code=201)
@router.post("/", response_model=dict, status_code=201, include_in_schema=False)
async def create_session(body: CreateSession) -> dict:
    return await session_store.create(
        kind=body.kind,
        name=body.name,
        title=body.title,
        workdir=body.workdir,
        scope_id=body.scope_id,
        metadata=body.metadata,
    )


@router.get("", response_model=list[SessionSummary])
@router.get("/", response_model=list[SessionSummary], include_in_schema=False)
async def list_sessions(
    kind: str | None = None,
    scope_id: str | None = None,
    top_level: bool = False,
) -> list[dict]:
    """List sessions.

    Filters (combinable):
      - ``kind``            only sessions of this kind
      - ``scope_id``        only members of this team scope
      - ``top_level=true``  only top-level sessions (scope_id IS NULL)
    With no filter, returns everything.
    """
    if top_level:
        return await session_store.list(kind=kind, scope_id=None)
    if scope_id is not None:
        return await session_store.list(kind=kind, scope_id=scope_id)
    return await session_store.list(kind=kind)


@router.get("/{session_id}")
async def get_session(session_id: str, request: Request) -> dict:
    """Session metadata + message history as an assistant-ui-compatible timeline.

    The history is read from the deepagents checkpointer for this thread and
    flattened into ThreadMessage-shaped entries the frontend MessagesStore can
    use directly:

      { role:'user'|'assistant', id, content:[ {type:'text',text} | {type:'tool-call',...} ] }

    An AIMessage may carry text AND tool_calls; each becomes a content part on
    the same assistant message, preserving the real text→tool ordering. A later
    ToolMessage back-fills the matching tool-call part's result.
    """
    s = await session_store.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")

    messages: list[dict] = []
    try:
        agent = request.app.state.agent
        snapshot = await agent.aget_state(
            {"configurable": {"thread_id": session_id}}
        )
        raw = (getattr(snapshot, "values", {}) or {}).get("messages", [])

        # tool_call_id -> (msg_index, part_index) so a ToolMessage can back-fill.
        tool_part_index: dict[str, tuple[int, int]] = {}

        for msg in raw:
            mtype = getattr(msg, "type", "")
            mid = getattr(msg, "id", None) or ""
            content = getattr(msg, "content", "")

            if mtype == "human":
                text = _content_to_text(content)
                if text.strip():
                    messages.append({
                        "role": "user", "id": mid or f"u-{len(messages)}",
                        "content": [{"type": "text", "text": text}],
                        "metadata": {"speaker": "user"},
                    })

            elif mtype == "ai":
                parts: list[dict] = []
                text = _content_to_text(content)
                if text.strip():
                    parts.append({"type": "text", "text": text})
                for tc in getattr(msg, "tool_calls", None) or []:
                    tcid = tc.get("id") or ""
                    parts.append({
                        "type": "tool-call",
                        "toolCallId": tcid,
                        "toolName": tc.get("name", "tool"),
                        "args": _stringify_args(tc.get("args")),
                        "result": None,
                    })
                    tool_part_index[tcid] = (len(messages), len(parts) - 1)
                # reasoning/thinking trace (GLM reasoning_content) — surfaced so
                # history reload shows the thinking region too.
                from ..engine import _extract_reasoning
                thinking = "".join(_extract_reasoning(msg))
                # include the message even if only thinking (no text/tool) so the
                # user can review prior reasoning on history reload.
                if parts or thinking:
                    msg_obj: dict = {
                        "role": "assistant",
                        "id": mid or f"a-{len(messages)}",
                        "content": parts,
                        "metadata": {"speaker": (s.get("name") or "Manus")},
                    }
                    if thinking:
                        msg_obj["thinking"] = thinking
                    messages.append(msg_obj)

            elif mtype == "tool":
                tcid = getattr(msg, "tool_call_id", "") or ""
                loc = tool_part_index.get(tcid)
                if loc is not None:
                    mi, pi = loc
                    messages[mi]["content"][pi]["result"] = _content_to_text(content)
    except Exception:
        # history is best-effort; never fail the whole response
        pass

    s["messages"] = messages
    return s


def _content_to_text(content: Any) -> str:
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        ).strip()
    return str(content) if content else ""


def _stringify_args(args: Any) -> str:
    if not args:
        return ""
    try:
        import json

        return json.dumps(args, ensure_ascii=False)
    except Exception:
        return str(args)


class UpdatePreview(BaseModel):
    preview: str
    speaker: str | None = None


@router.patch("/{session_id}")
async def update_session(session_id: str, body: UpdateSession) -> dict:
    s = await session_store.update(
        session_id,
        title=body.title,
        status=body.status,
        workdir=body.workdir,
        metadata=body.metadata,
    )
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    return s


@router.post("/{session_id}/preview")
async def set_preview(session_id: str, body: UpdatePreview) -> dict:
    """Set the session's last-message preview (and optionally speaker).

    Merged into metadata (NOT a full overwrite) so existing metadata like
    parent/role/members is preserved.
    """
    existing = await session_store.get(session_id)
    if not existing:
        raise HTTPException(status_code=404, detail="session not found")
    md = dict(existing.get("metadata") or {})
    md["preview"] = (body.preview or "")[:120]
    if body.speaker:
        md["preview_speaker"] = body.speaker
    s = await session_store.update(session_id, metadata=md)
    return s or existing


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    ok = await session_store.delete(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": session_id}


@router.post("/{session_id}/reset")
async def reset_session(session_id: str, request: Request) -> dict:
    """Reset a session's conversation history (clear the checkpointer thread).

    Used by the default entry's "new chat": the default item is permanent and
    can't be deleted, so starting fresh means wiping its message history. The
    session row itself is untouched.
    """
    if not await session_store.get(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    try:
        agent = request.app.state.agent
        checkpointer = getattr(agent, "checkpointer", None)
        if checkpointer is not None and hasattr(checkpointer, "adelete_thread"):
            await checkpointer.adelete_thread(session_id)
    except Exception:
        pass
    return {"reset": session_id}


# --- Mailbox + whiteboard views (per session / per scope) -------------------

@router.get("/{session_id}/mailbox")
async def get_mailbox(session_id: str, unread_only: bool = False) -> dict:
    """A participant's inbox (inter-agent messages). Powers the chat/task view."""
    if not await session_store.get(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    from ..mailbox import mailbox_store

    msgs = await mailbox_store.inbox(session_id, unread_only=unread_only)
    return {"session_id": session_id, "messages": msgs}


@router.get("/{session_id}/whiteboard")
async def get_whiteboard(session_id: str) -> dict:
    """Artefacts in this session's scope + the artefacts it authored."""
    s = await session_store.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    from ..whiteboard import whiteboard_store

    scope_id = s.get("scope_id")
    in_scope = await whiteboard_store.list_in_scope(scope_id) if scope_id else []
    authored = await whiteboard_store.list_by_author(session_id)
    return {"session_id": session_id, "scope_id": scope_id, "in_scope": in_scope, "authored": authored}


# --- Workdir validation (top-level, not under /sessions) --------------------
workdir_router = APIRouter(tags=["workdir"])


class ValidateWorkdir(BaseModel):
    path: str


@workdir_router.post("/workdir/validate")
async def validate_workdir(body: ValidateWorkdir) -> dict:
    """Check that a workdir path exists and is a directory."""
    from pathlib import Path

    p = Path(body.path).expanduser()
    exists = p.exists()
    is_dir = p.is_dir()
    entries: list[str] = []
    if is_dir:
        try:
            entries = sorted([e.name for e in p.iterdir()])[:12]
        except (PermissionError, OSError):
            entries = []
    return {
        "path": str(p),
        "exists": exists,
        "is_dir": is_dir,
        "valid": exists and is_dir,
        "entries": entries,
    }
