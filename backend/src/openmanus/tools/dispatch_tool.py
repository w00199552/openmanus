"""Dispatch tool — the control-flow side of agent delegation.

Dispatch and mailbox are SEPARATE concerns (this split is deliberate; see the
plan in the dispatch/mailbox decoupling work):

  * **dispatch** (this module) = control flow. It creates a child agent session,
    inherits the caller's workdir + scope, and starts the child running with a
    `Task:` prompt (via engine.start / engine.run). It does NOT send mailbox
    messages — sending one would trigger _wakeup on the idle child and start a
    duplicate inbox turn alongside the Task-prompt turn.
  * **mailbox** (`mailbox_tools.py`) = communication flow. send_message /
    read_mailbox tools for peer-to-peer chat between running agents.

ONE dispatch tool handles both delegation shapes:
  - target_agent="TeamLeader" → create a team session (scope root) + run it
  - target_agent="Coder"/"Researcher" → create a subagent session + run it

Each dispatch builds a BRAND-NEW agent instance (build_agent) — never reuses a
graph. This keeps every agent's run fully isolated (the cross-talk fix).

Manus only has this one dispatch tool. TeamLeader also has send_message /
read_mailbox / whiteboard tools (for peer chat inside the team).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolArg
from pydantic import BaseModel, Field

from ..agent_loader import agent_loader
from ..db import session_store

logger = logging.getLogger(__name__)


def _config_session_id(config: RunnableConfig | None) -> str:
    return ((config or {}).get("configurable") or {}).get("thread_id") or "unknown"


class DispatchInput(BaseModel):
    target_agent: str = Field(
        description=(
            "Name of the agent to delegate to. Available agents are listed in "
            "this tool's description. Use the exact name."
        )
    )
    task: str = Field(
        description=(
            "The full task to hand off. Be detailed — this is the only context "
            "the agent receives. Include goals, file paths, constraints."
        )
    )


def _build_agent_registry() -> str:
    """Build a human-readable list of available agents from agent_loader.

    Includes each agent's name + description, so the LLM knows exactly who it
    can dispatch to. Called at tool-construction time (once per agent build).
    """
    lines = []
    for name in sorted(agent_loader.all_names()):
        cfg = agent_loader.get(name) or {}
        desc = cfg.get("description", "").strip()
        if desc:
            lines.append(f"  - {name}: {desc}")
        else:
            lines.append(f"  - {name}")
    return "\n".join(lines)


def make_dispatch_tool(*, workdir: str, **_kw) -> BaseTool:
    """Build the unified dispatch tool.

    Each dispatch creates a FRESH agent (build_agent) for the target role —
    independent graph, isolated from the caller. The dispatched agent runs
    AFTER the caller's astream finishes (deferred via engine.start) — never
    concurrently. Results come back via mailbox "result" messages (handled by
    engine._record_result), which the caller reads on its next turn.
    """

    # Dynamically list available agents so the LLM knows who it can dispatch to.
    agent_registry = _build_agent_registry()

    async def dispatch(
        target_agent: str,
        task: str,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Delegate a task to another agent. Returns immediately; the agent
        runs in the background. Check read_mailbox later for the result.

        Available agents (use the exact name as target_agent):
        """
        if not agent_loader.get(target_agent):
            return f"Unknown agent '{target_agent}'. Available: {', '.join(agent_loader.all_names())}."
        from ..engine import engine  # lazy: avoid import cycle

        caller_session_id = _config_session_id(config)
        caller_row = await session_store.get(caller_session_id)
        caller_scope = (caller_row or {}).get("scope_id")
        # Inherit caller's workdir (supports /cd command — child works in the
        # same directory as the caller, not the global settings.workdir).
        caller_workdir = (caller_row or {}).get("workdir") or workdir

        # ── TeamLeader: create a team session (scope root) ──
        if target_agent.lower() == "teamleader":
            team = await session_store.create(
                kind="team",
                name=target_agent,
                title=task[:60] or "team task",
                workdir=caller_workdir,
                scope_id=None,
                metadata={
                    "parent": caller_session_id,
                    "members": ["TeamLeader", "Researcher", "Coder"],
                },
            )
            team_id = team["id"]
            await session_store.update(team_id, status="running")
            await engine.run(
                session_id=team_id, prompt=task,
                speaker=target_agent, mode="async",
            )
            return (
                f"Delegated to team {team_id}. The team is working in the "
                f"background. Tell the user they can open team {team_id[:12]}."
            )

        # ── specialist (Coder/Researcher): create a session ──
        if caller_row and caller_row.get("kind") == "team":
            scope_id = caller_session_id
        else:
            scope_id = caller_scope

        # Specialists write directly into the caller's workdir — no per-agent
        # subdirectory. This matches the TeamLeader branch and keeps all
        # artifacts in one place unless the task itself requests otherwise.
        child = await session_store.create(
            kind="subagent",
            name=target_agent,
            title=task[:60] or f"{target_agent} task",
            workdir=caller_workdir,
            scope_id=scope_id,
            metadata={
                "role": target_agent,
                "parent": caller_session_id,
            },
        )
        child_id = child["id"]

        await engine.start(
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

    # Inject the agent list into the docstring so the LLM sees all available agents.
    dispatch.__doc__ = (dispatch.__doc__ or "") + agent_registry
    # Wrap with @tool to register as a LangChain tool.
    return tool("dispatch", args_schema=DispatchInput)(dispatch)
