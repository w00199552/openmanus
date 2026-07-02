"""Whiteboard tools: let agents write/read shared communication artefacts.

These are the "communication layer" tools — distinct from the sandbox file
tools (read_file/write_file/...). An agent writes a whiteboard artefact when it
wants OTHER agents to consume a structured result without the parent having to
pass the whole text through its own context (the "game of telephone" problem
Claude Code's artefact pattern solves).

Soft-structured: ``kind`` is a free tag the model picks (research / plan /
diff-summary / …), not an enforced enum. Content is free text or JSON.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolArg
from pydantic import BaseModel, Field

from ..db import session_store
from ..whiteboard import whiteboard_store

logger = logging.getLogger(__name__)


class WhiteboardWriteInput(BaseModel):
    title: str = Field(description="A short title for this artefact.")
    content: str = Field(
        description=(
            "The artefact body — free text or JSON. This is the structured "
            "result other agents will read. Be complete; it persists."
        )
    )
    kind: str = Field(
        default="result",
        description=(
            "A free-form tag describing this artefact, e.g. 'research', "
            "'plan', 'diff-summary', 'result'. Helps other agents find it."
        ),
    )


def make_whiteboard_write_tool(
    *, session_id_fn: Any, scope_id_fn: Any
) -> BaseTool:
    """Build the whiteboard-write tool.

    ``session_id_fn`` / ``scope_id_fn`` are zero-arg callables that resolve the
    CURRENT agent's session id / scope at call time (from the runnable config).
    We take callables (not values) because the tool is built once but the
    running session changes per call.
    """

    @tool("whiteboard_write", args_schema=WhiteboardWriteInput)
    async def whiteboard_write(
        title: str,
        content: str,
        kind: str = "result",
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Write a structured artefact to the team whiteboard for other agents.

        Use this to publish a result/findings/plan that another agent should
        read, instead of returning a huge block of text through the
        conversation. Returns the artefact id (a short reference others pass to
        whiteboard_read).
        """
        sid = session_id_fn(config)
        # The author's scope: their own session's scope_id (the team they're in).
        s = await session_store.get(sid)
        scope_id = (s or {}).get("scope_id") if s else scope_id_fn(config)
        if not scope_id:
            return (
                "No shared whiteboard for this context (no team scope). Write "
                "to a file in the sandbox instead, or return the text directly."
            )
        art = await whiteboard_store.create(
            scope_id=scope_id, session_id=sid, kind=kind or "result",
            title=title, content=content,
        )
        return f"Wrote whiteboard artefact {art['id']} (kind={kind}). Other agents can read it with whiteboard_read."

    return whiteboard_write


class WhiteboardReadInput(BaseModel):
    artefact_id: str | None = Field(
        default=None,
        description=(
            "The specific artefact id to read. If omitted, lists all "
            "artefacts in the current team scope (with ids + titles)."
        ),
    )
    kind: str | None = Field(
        default=None,
        description="Optional filter when listing (e.g. only 'research' artefacts).",
    )


def make_whiteboard_read_tool(*, scope_id_fn: Any) -> BaseTool:
    """Build the whiteboard-read tool."""

    @tool("whiteboard_read", args_schema=WhiteboardReadInput)
    async def whiteboard_read(
        artefact_id: str | None = None,
        kind: str | None = None,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Read a whiteboard artefact by id, or list the team's artefacts.

        Pass an artefact_id to fetch its full content. Omit it to see a
        summary list (id + kind + title) of everything in the current scope.
        """
        if artefact_id:
            art = await whiteboard_store.get(artefact_id)
            if not art:
                return f"No artefact with id {artefact_id}."
            return (
                f"Artefact {art['id']} (kind={art.get('kind')}, by {art.get('session_id')}):\n"
                f"{art.get('content') or '(empty)'}"
            )
        scope_id = scope_id_fn(config)
        if not scope_id:
            return "No shared whiteboard in this context."
        arts = await whiteboard_store.list_in_scope(scope_id, kind=kind)
        if not arts:
            return "No whiteboard artefacts in this scope yet."
        lines = [f"- {a['id']} [{a.get('kind')}] {a.get('title') or ''}" for a in arts]
        return "Whiteboard artefacts:\n" + "\n".join(lines)

    return whiteboard_read
