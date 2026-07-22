"""Whiteboard tools — the topic-scoped task board for agents.

These are the COMMUNICATION tools. An agent uses them to publish structured
artefacts (research / plan / task / result) onto the shared whiteboard so
OTHER agents can consume them, instead of stuffing the whole result through
the conversation (the "game of telephone" problem the artefact pattern
solves).

Soft-structured: ``kind`` is a free tag the model picks (not an enforced
enum); ``status`` is a small workflow enum (pending / in_progress / finished
/ error). The topic_id and author are resolved from the runnable config at
call time via injected callables, mirroring dispatch_tool.py /
mailbox_tools.py (built once, used across many sessions).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Callable, Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolArg
from pydantic import BaseModel, Field

from ..whiteboard import whiteboard_store

logger = logging.getLogger(__name__)

# A callable that pulls a value out of a RunnableConfig at call time. Mirrors
# the session_id_fn / scope_id_fn pattern used by dispatch_tool.py /
# mailbox_tools.py — the tool is built once but resolves the live value per
# invocation (so it works across many sessions/topics).
ConfigFn = Callable[[RunnableConfig | None], Any]


def make_whiteboard_write_tool(*, topic_id_fn: ConfigFn, author_fn: ConfigFn) -> BaseTool:
    """Build the whiteboard-write tool.

    ``topic_id_fn`` / ``author_fn`` read the CURRENT topic_id and author from
    the runnable config at call time (see agent_factory._resolve_topic_id and
    config["configurable"]["agent_name"]). Callables are used instead of plain
    values because the tool is built once but the live topic/author changes
    per invocation.
    """

    class WhiteboardWriteInput(BaseModel):
        title: str = Field(description="A short title for this note.")
        content: str = Field(
            description=(
                "The note body — free text or JSON. This is the structured "
                "result other agents will read. Be complete; it persists."
            )
        )
        kind: str = Field(
            default="task",
            description=(
                "A free-form tag describing this note, e.g. 'task', 'plan', "
                "'research', 'result'. Helps other agents find it."
            ),
        )

    @tool("whiteboard_write", args_schema=WhiteboardWriteInput)
    async def whiteboard_write(
        title: str,
        content: str,
        kind: str = "task",
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Write a structured note to the topic whiteboard.

        Use this to publish a task/plan/research/result that other agents
        should read, instead of returning a large block of text through the
        conversation. Returns the new note id.
        """
        topic_id = topic_id_fn(config)
        author = author_fn(config)
        if not topic_id:
            return (
                "No topic whiteboard in this context. Write to a file in the "
                "sandbox instead, or return the text directly."
            )
        note = await whiteboard_store.create(
            topic_id=topic_id,
            author=author or "unknown",
            kind=kind or "task",
            title=title,
            content=content,
        )
        return (
            f"Wrote whiteboard note {note['id']} (kind={kind}, status=pending). "
            "Others can read it with whiteboard_read."
        )

    return whiteboard_write


def make_whiteboard_update_status_tool() -> BaseTool:
    """Build the whiteboard status-update tool."""

    class WhiteboardUpdateStatusInput(BaseModel):
        note_id: str = Field(description="The id of the whiteboard note to update.")
        status: Literal["pending", "in_progress", "finished", "error"] = Field(
            description="The new workflow status for the note."
        )

    @tool("whiteboard_update_status", args_schema=WhiteboardUpdateStatusInput)
    async def whiteboard_update_status(
        note_id: str,
        status: Literal["pending", "in_progress", "finished", "error"],
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Update the workflow status of a whiteboard note."""
        note = await whiteboard_store.update_status(note_id, status)
        if not note:
            return f"No whiteboard note with id {note_id}."
        return f"Updated note {note_id} to status='{status}'."

    return whiteboard_update_status


def make_whiteboard_read_tool(*, topic_id_fn: ConfigFn) -> BaseTool:
    """Build the whiteboard-read tool.

    Pass a ``note_id`` to fetch its full content; omit it to list all notes
    in the current topic (optionally filtered by status).
    """

    class WhiteboardReadInput(BaseModel):
        note_id: str | None = Field(
            default=None,
            description=(
                "The specific note id to read. If omitted, lists all notes "
                "in the current topic (with ids + titles)."
            ),
        )
        status: Literal["pending", "in_progress", "finished", "error"] | None = Field(
            default=None,
            description="Optional filter when listing (e.g. only 'pending' notes).",
        )

    @tool("whiteboard_read", args_schema=WhiteboardReadInput)
    async def whiteboard_read(
        note_id: str | None = None,
        status: Literal["pending", "in_progress", "finished", "error"] | None = None,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Read a whiteboard note by id, or list the topic's notes.

        Pass a note_id to fetch its full content. Omit it to see a summary
        list (id + status + kind + title) of everything in the current topic.
        """
        if note_id:
            note = await whiteboard_store.get(note_id)
            if not note:
                return f"No whiteboard note with id {note_id}."
            return (
                f"Note {note['id']} (kind={note.get('kind')}, "
                f"status={note.get('status')}, by {note.get('author')}):\n"
                f"{note.get('content') or '(empty)'}"
            )
        topic_id = topic_id_fn(config)
        if not topic_id:
            return "No topic whiteboard in this context."
        notes = await whiteboard_store.list_in_topic(topic_id, status=status)
        if not notes:
            return "No whiteboard notes in this topic yet."
        lines = [
            f"- {n['id']} [{n.get('status')}/{n.get('kind')}] "
            f"{n.get('title') or ''}"
            for n in notes
        ]
        return "Whiteboard notes:\n" + "\n".join(lines)

    return whiteboard_read
