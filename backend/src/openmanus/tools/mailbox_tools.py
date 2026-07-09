"""Mailbox tools: agent-to-agent messaging + the unified dispatch tool.

ONE dispatch tool handles both cases:
  - target_agent="teamleader" → create a team session + run a fresh teamleader
  - target_agent="coder"/"researcher" → create a session + run a fresh agent

Each dispatch builds a BRAND-NEW agent instance (build_agent) — never reuses a
graph. This keeps every agent's run fully isolated (the cross-talk fix).

manus only has this one dispatch tool (no separate dispatch_to_team).
teamleader also has send_message / read_mailbox / whiteboard tools.
"""

from __future__ import annotations

import logging
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolArg
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Annotated, Any

from ..agent_loader import agent_loader
from ..db import session_store
from ..mailbox import mailbox_store

logger = logging.getLogger(__name__)


def _config_session_id(config: RunnableConfig | None) -> str:
    return ((config or {}).get("configurable") or {}).get("thread_id") or "unknown"


class DispatchInput(BaseModel):
    target_agent: str = Field(
        description=(
            "Which agent to delegate to: 'coder' (read/edit/run files), "
            "'researcher' (read-only investigation), or 'teamleader' "
            "(coordinates a team for complex multi-step tasks)."
        )
    )
    task: str = Field(
        description=(
            "The full task to hand off. Be detailed — this is the only context "
            "the agent receives. Include goals, file paths, constraints."
        )
    )


def make_dispatch_tool(*, workdir: str, **_kw) -> BaseTool:
    """Build the unified dispatch tool.

    Each dispatch creates a FRESH agent (build_agent) for the target role —
    independent graph, isolated from the caller. The dispatched agent runs
    AFTER the caller's astream finishes (deferred) — never concurrently.
    Results come back via mailbox (the caller reads them on its next turn).
    """

    @tool("dispatch", args_schema=DispatchInput)
    async def dispatch(
        target_agent: str,
        task: str,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Delegate a task to another agent. Returns immediately; the agent
        runs in the background. Check read_mailbox later for the result.

        - target_agent='coder'/'researcher': a single specialist runs the task.
        - target_agent='teamleader': a team is created; the leader coordinates
          further specialists. Use this for complex multi-step work.
        """
        if not agent_loader.get(target_agent):
            return f"Unknown agent '{target_agent}'. Available: {', '.join(agent_loader.all_names())}."
        from ..engine import engine  # lazy: avoid import cycle
        from ..agent_factory import build_agent

        caller_session_id = _config_session_id(config)
        caller_row = await session_store.get(caller_session_id)
        caller_scope = (caller_row or {}).get("scope_id")
        # Inherit caller's workdir (supports /cd command — child works in the
        # same directory as the caller, not the global settings.workdir).
        caller_workdir = (caller_row or {}).get("workdir") or workdir

        # ── teamleader: create a team session (scope root) ──
        if target_agent.lower() == "teamleader":
            team = await session_store.create(
                kind="team",
                name=target_agent,
                title=task[:60] or "team task",
                workdir=caller_workdir,
                scope_id=None,
                metadata={
                    "parent": caller_session_id,
                    "members": ["teamleader", "researcher", "coder"],
                },
            )
            team_id = team["id"]
            await session_store.update(team_id, status="running")
            team_agent = await build_agent(target_agent, caller_workdir)
            await engine.run(
                agent=team_agent, session_id=team_id, prompt=task,
                speaker=target_agent, mode="async",
            )
            await mailbox_store.send(
                to_session_id=team_id, from_session_id=caller_session_id,
                kind="dispatch", content=task,
            )
            return (
                f"Delegated to team {team_id}. The team is working in the "
                f"background. Tell the user they can open team {team_id[:12]}."
            )

        # ── specialist (coder/researcher): create a session ──
        if caller_row and caller_row.get("kind") == "team":
            scope_id = caller_session_id
        else:
            scope_id = caller_scope

        child_workdir = str(Path(caller_workdir) / "agents" / target_agent)
        Path(child_workdir).mkdir(parents=True, exist_ok=True)

        child = await session_store.create(
            kind="subagent",
            name=target_agent,
            title=task[:60] or f"{target_agent} task",
            workdir=child_workdir,
            scope_id=scope_id,
            metadata={
                "role": target_agent,
                "allowed_tools": sorted(agent_loader.get(target_agent).get("allowed_tools", set())),
                "parent": caller_session_id,
            },
        )
        child_id = child["id"]

        sub_agent = await build_agent(target_agent, child_workdir)  # noqa: same var, different context
        await engine.start(
            agent=sub_agent,
            caller_session_id=caller_session_id,
            target_agent=target_agent,
            task=task,
            scope_id=scope_id,
            target_session_id=child_id,
        )
        return (
            f"Delegated to {target_agent} (task {child_id[:12]}), running in the "
            f"background. Use read_mailbox later to check the result."
        )

    return dispatch


def make_send_message_tool() -> BaseTool:
    class SendMessageInput(BaseModel):
        to_agent_session_id: str = Field(description="The session id of the agent to message.")
        content: str = Field(description="The message text.")

    @tool("send_message", args_schema=SendMessageInput)
    async def send_message(
        to_agent_session_id: str,
        content: str,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Send a short chat message to another agent in your team."""
        await mailbox_store.send(
            to_session_id=to_agent_session_id,
            from_session_id=_config_session_id(config),
            kind="chat",
            content=content,
        )
        return f"Sent message to {to_agent_session_id[:12]}."

    return send_message


def make_read_mailbox_tool() -> BaseTool:
    @tool("read_mailbox")
    async def read_mailbox(
        unread_only: bool = False,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Read messages in your inbox (tasks, peer chat, results)."""
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
