"""Mailbox tools: agent-to-agent messaging + the unified dispatch primitive.

Replaces the old dispatch_single / dispatch_to_team / dispatch_task trio with
ONE ``dispatch`` tool plus send_message / read_mailbox for free-form inter-agent
chat. The unified model: agents communicate by sending messages to each other's
mailboxes; delegation is just a dispatch-kind message followed by running the
target agent on its own session/channel.

dispatch modes (the sync/async decision lives with the CALLER):
  * ``mode="async"``  — return immediately with the child session id. The
                        entry default agent uses this (fire-and-forget; the user
                        watches the new task in the list).
  * ``mode="sync"``   — block until the sub-agent finishes and return its final
                        text. The teamleader uses this for serial orchestration
                        (next decision needs this result), or async when several
                        independent sub-tasks can run together.

The sub-agent always runs on the SHARED agent graph that still has filesystem
tools (the teamleader's graph) — the default agent's own graph has those tools
stripped by ToolGuard, so a coder couldn't do its job there. The role is
applied via the role prompt prepended to the task (researcher / coder).
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolArg
from pydantic import BaseModel, Field

from ..db import session_store
from ..mailbox import mailbox_store
from .roles import ROLES

logger = logging.getLogger(__name__)


def _config_session_id(config: RunnableConfig | None) -> str:
    return ((config or {}).get("configurable") or {}).get("thread_id") or "unknown"


class DispatchInput(BaseModel):
    target_agent: str = Field(
        description=(
            "Which specialist to delegate to: 'coder' (read/edit/run files) "
            "or 'researcher' (read-only investigation)."
        )
    )
    task: str = Field(
        description=(
            "The full task to hand off. Be detailed — this is the only context "
            "the sub-agent receives. Include goals, file paths, constraints."
        )
    )
    mode: str = Field(
        default="async",
        description=(
            "'async' (default): return immediately with the task id; watch it in "
            "the task list. 'sync': wait for the sub-agent to finish and return "
            "its result text. Use sync only when your next step needs this "
            "result; use async for independent parallel work."
        ),
    )


def make_dispatch_tool(*, agent_ref: Any, workdir: str, default_mode: str = "async") -> BaseTool:
    """Build the unified dispatch tool.

    ``agent_ref`` holds the compiled agent graph the sub-agent runs on (the
    teamleader's graph, which keeps filesystem tools). ``workdir`` is the
    parent workdir (a per-role subdir is created under it). ``default_mode`` is
    the mode used when the caller doesn't pass one (the entry default agent
    defaults to async; the teamleader can override per call).
    """

    @tool("dispatch", args_schema=DispatchInput)
    async def dispatch(
        target_agent: str,
        task: str,
        mode: str = "",
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Delegate a task to a specialist sub-agent (coder/researcher).

        Async by default — returns the new task id immediately and the user can
        watch it run in the task list. Pass mode='sync' to block for the result
        (use when your next decision depends on it).
        """
        if target_agent not in ROLES:
            return (
                f"Unknown agent '{target_agent}'. Available: {', '.join(ROLES.keys())}."
            )
        from ..runner import runner  # lazy: avoid import cycle

        run_mode = mode or default_mode
        parent_session_id = _config_session_id(config)
        parent_row = await session_store.get(parent_session_id)
        parent_scope = (parent_row or {}).get("scope_id")

        # If the parent IS a team session, the child lives in that team's scope.
        # Otherwise (default agent dispatching a single specialist) the child is
        # top-level (scope_id NULL) — it shows in the task list on its own.
        if parent_row and parent_row.get("kind") == "team":
            scope_id = parent_session_id
        else:
            scope_id = parent_scope  # may be None for top-level single dispatch

        # Per-role workdir subdir (OpenClaw agentDir style).
        child_workdir = str(Path(workdir) / "agents" / target_agent)
        Path(child_workdir).mkdir(parents=True, exist_ok=True)

        child = await session_store.create(
            kind="subagent",
            name=target_agent,
            title=task[:60] or f"{target_agent} task",
            workdir=child_workdir,
            scope_id=scope_id,
            metadata={
                "role": target_agent,
                "allowed_tools": sorted(ROLES[target_agent]["allowed_tools"]),
                "parent": parent_session_id,
            },
        )
        child_id = child["id"]

        agent = agent_ref["agent"] if isinstance(agent_ref, dict) else agent_ref
        result = await runner.dispatch(
            agent=agent,
            from_session_id=parent_session_id,
            target_agent=target_agent,
            task=task,
            scope_id=scope_id,
            child_session_id=child_id,
            mode=run_mode,
        )

        if run_mode == "sync":
            preview = (result or "")[:200]
            return (
                f"[{target_agent}] completed. Result:\n{preview}"
                if result else f"[{target_agent}] completed (no text output)."
            )
        return (
            f"Delegated to {target_agent} (task {child_id[:12]}), running in the "
            f"background. Tell the user they can open task {child_id[:12]} to watch it."
        )

    return dispatch


def make_start_team_tool(*, team_agent_ref: Any, workdir: str) -> BaseTool:
    """Build the dispatch_to_team tool (default agent → background team).

    Creates a team session (scope) and runs the teamleader on it in the
    background. The teamleader then coordinates its own sub-agents via dispatch
    (sync or async as it sees fit).
    """

    @tool("dispatch_to_team")
    async def dispatch_to_team(
        task: str,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Delegate a large/multi-step task to a background team.

        Use when a task needs several specialists coordinating. Returns
        immediately with a team id; the user opens the team chat to watch.
        """
        from ..runner import runner  # lazy

        default_session_id = _config_session_id(config)
        team = await session_store.create(
            kind="team",
            name="teamleader",
            title=task[:60] or "team task",
            scope_id=None,  # a team is its own scope root
            metadata={
                "parent": default_session_id,
                "members": ["teamleader", "researcher", "coder"],
            },
        )
        team_id = team["id"]
        await session_store.update(team_id, status="running")

        team_agent = (
            team_agent_ref["agent"] if isinstance(team_agent_ref, dict) else team_agent_ref
        )
        # Run the teamleader async on its own session/channel.
        await runner.run(
            agent=team_agent, session_id=team_id, prompt=task,
            speaker="teamleader", mode="async",
        )
        return (
            f"Delegated to team {team_id}. The team is working in the background. "
            f"Tell the user they can open team {team_id[:12]} to watch the group chat."
        )

    return dispatch_to_team


class SendMessageInput(BaseModel):
    to_agent_session_id: str = Field(
        description="The session id of the agent to message (a peer in your scope)."
    )
    content: str = Field(description="The message text.")


def make_send_message_tool() -> BaseTool:
    """Free-form inter-agent chat (non-delegation talk)."""

    @tool("send_message", args_schema=SendMessageInput)
    async def send_message(
        to_agent_session_id: str,
        content: str,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Send a short chat message to another agent in your team.

        Use this for coordination talk that isn't a task delegation (e.g. asking
        a peer a question, reporting a partial finding). For handing off work,
        use dispatch.
        """
        from_session_id = _config_session_id(config)
        await mailbox_store.send(
            to_session_id=to_agent_session_id,
            from_session_id=from_session_id,
            kind="chat",
            content=content,
        )
        return f"Sent message to {to_agent_session_id[:12]}."

    return send_message


def make_read_mailbox_tool() -> BaseTool:
    """Let an agent read its own inbox (dispatches/results/chat from peers)."""

    @tool("read_mailbox")
    async def read_mailbox(
        unread_only: bool = False,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Read messages in your inbox (tasks delegated to you, peer chat, results).

        Pass unread_only=true to see only new messages. Returns a compact list;
        each entry shows the sender, kind, and content (or whiteboard ref for
        results).
        """
        sid = _config_session_id(config)
        msgs = await mailbox_store.inbox(sid, unread_only=unread_only)
        if not msgs:
            return "Inbox empty."
        lines = []
        for m in msgs:
            tail = m.get("content") or ""
            if m.get("whiteboard_ref"):
                tail += f" (whiteboard: {m['whiteboard_ref']})"
            lines.append(f"[{m['kind']}] from {str(m['from_session_id'])[:12]}: {tail}")
        return "Inbox:\n" + "\n".join(lines)

    return read_mailbox
