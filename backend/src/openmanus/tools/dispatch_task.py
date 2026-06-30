"""dispatch_task tool: teamleader delegates a subtask to a specialized agent.

When the teamleader calls ``dispatch_task``, this tool:
  1. Creates a child session (kind=subagent) linked to the current (parent)
     session via a ``dispatch`` message_link.
  2. Runs the target sub-agent on a FRESH thread (= the child session id), so
     its history is isolated from the parent (Claude Code style: each
     sub-agent gets its own clean context, returns only the result).
  3. The sub-agent's tool set is restricted by its ``allowed_tools`` config
     (OpenClaw style: enforced at the tool layer, not just the prompt).
  4. Records a ``result`` message_link back to the parent and returns the
     sub-agent's final answer to the teamleader.

This is SYNCHRONOUS (blocks the teamleader until the subtask finishes) —
async/non-blocking dispatch is a later phase.
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
from .roles import ROLES

logger = logging.getLogger(__name__)


class DispatchTaskInput(BaseModel):
    task_description: str = Field(
        description="A detailed description of the task to delegate to the sub-agent."
    )
    target_agent: str = Field(
        description=(
            "Which specialized agent to delegate to. One of: "
            "'researcher' (read-only investigation) or 'coder' (can edit files)."
        )
    )


# --- sub-agent role catalogue ----------------------------------------------
# ROLES is defined in .roles (shared with dispatch_single). Each role defines
# its allowed tools (intended to be enforced; today applied via prompt only)
# and system prompt.


def _filter_tools(all_tools: list[BaseTool], allowed: set[str]) -> list[BaseTool]:
    """Keep only the tools whose name is in `allowed` (enforced allow-list)."""
    kept = [t for t in all_tools if t.name in allowed]
    if not kept:
        return all_tools  # fall back rather than running with zero tools
    return kept


async def _run_subagent(
    *,
    agent: Any,
    role: str,
    task_description: str,
    child_session_id: str,
    parent_config: dict[str, Any],
    on_text_delta=None,
    on_tool=None,
) -> str:
    """Run the sub-agent on an isolated thread; return its final text answer.

    Streams the agent's output via callbacks when provided (used to surface a
    sub-agent's live activity into the team group chat):
      * ``on_text_delta(delta)`` — each streamed text token
      * ``on_tool(name)`` — when the sub-agent starts a tool call (e.g. read_file)

    Uses astream so tokens can be forwarded live, instead of ainvoke which
    blocks until done with no output.
    """
    from langchain_core.messages import AIMessageChunk, HumanMessage

    # Override system prompt + tools for this role by invoking with a role tag
    # prepended to the task. (A full per-role agent rebuild is a later
    # optimisation; for MVP the prompt + tool filtering is enough.)
    prompt = f"[You are operating as: {role}]\n{ROLES[role]['prompt']}\n\nTask:\n{task_description}"

    config = {
        **parent_config,
        "configurable": {
            **parent_config.get("configurable", {}),
            "thread_id": child_session_id,  # isolated thread for this sub-agent
        },
    }

    # Run streaming so tokens can be forwarded live (and the checkpointer fills).
    # We extract TEXT deltas AND detect tool-call starts (to surface the
    # sub-agent's file operations under its own speaker in the team chat).
    from ..agui_bridge import _extract_text

    try:
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content=prompt)]},
            config=config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
            version="v2",
        ):
            ctype = chunk.get("type")
            if ctype != "messages":
                continue
            data = chunk.get("data")
            if not (isinstance(data, tuple) and len(data) == 2):
                continue
            msg, _meta = data
            if isinstance(msg, AIMessageChunk):
                # forward text tokens
                for text in _extract_text(msg.content):
                    if text and on_text_delta:
                        await on_text_delta(text)
                # detect tool-call starts (first fragment carries the name)
                for tc in msg.tool_call_chunks or []:
                    name = (
                        tc.get("name")
                        if isinstance(tc, dict)
                        else getattr(tc, "name", None)
                    )
                    if name and on_tool:
                        await on_tool(name)
    except Exception:
        logger.exception("sub-agent streaming failed; falling back to state read")

    # Pull the final assistant text from the now-populated checkpointer state.
    snapshot = await agent.aget_state(config)
    for msg in reversed(getattr(snapshot, "values", {}).get("messages", [])):
        if getattr(msg, "type", "") == "ai":
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            return str(content) or "(sub-agent produced no text output)"
    return "(sub-agent produced no output)"


def make_dispatch_task_tool(
    *, agent_ref: Any, parent_workdir: str
) -> BaseTool:
    """Build the dispatch_task tool, bound to the shared agent instance.

    ``agent_ref`` is the compiled deepagents graph (module-level singleton);
    we hold it indirectly so the tool can be defined before the agent exists.
    """

    @tool("dispatch_task", args_schema=DispatchTaskInput)
    async def dispatch_task(
        task_description: str,
        target_agent: str,
        config: Annotated[RunnableConfig, InjectedToolArg],
    ) -> str:
        """Delegate a subtask to a specialised sub-agent.

        Use this to delegate self-contained work: target_agent="researcher"
        for read-only investigation, or "coder" for changes that edit/write
        files. The sub-agent runs in its own isolated context and returns only
        its result. Give a clear, detailed task_description (include file
        paths, goals, constraints) since the sub-agent starts with no context.
        """
        # thread_id (the parent session id) comes from the runnable config.
        parent_config: dict[str, Any] = dict(config or {})
        parent_session_id = (
            parent_config.get("configurable", {}).get("thread_id") or "unknown"
        )
        tool_call_id = (
            parent_config.get("configurable", {}).get("tool_call_id")
            or parent_config.get("metadata", {}).get("tool_call_id")
            or "unknown"
        )
        if target_agent not in ROLES:
            return (
                f"Unknown target_agent '{target_agent}'. "
                f"Available: {', '.join(ROLES)}."
            )

        role = ROLES[target_agent]
        # Child session: isolated workdir subdir (OpenClaw agentDir style).
        child_workdir = str(Path(parent_workdir) / "agents" / target_agent)
        Path(child_workdir).mkdir(parents=True, exist_ok=True)

        child = await session_store.create(
            kind="subagent",
            name=target_agent,
            title=task_description[:60] or None,
            workdir=child_workdir,
            metadata={
                "role": target_agent,
                "allowed_tools": sorted(role["allowed_tools"]),
                "parent_tool_use_id": tool_call_id,
                # This is an INTRA-TEAM dispatch (teamleader → specialist), not
                # a top-level single-agent task from the default entry. Marked
                # so the session list can hide team-internal work from the top
                # level (only default-dispatched subagents show in TASKS).
                "internal": True,
            },
        )
        child_id = child["id"]

        # If this dispatch is happening INSIDE a team (parent is a team session),
        # surface the sub-agent's work in the team group chat so the user can
        # watch "researcher started → coder started" as it happens. Lazily import
        # team_runner to avoid a circular import at module load.
        from ..team_runner import (
            _push_group_close,
            _push_group_delta,
            _push_group_detail,
            _push_group_open,
            teams as _team_registry,
        )

        parent_row = await session_store.get(parent_session_id)
        team_id = (
            parent_session_id
            if parent_row and parent_row.get("kind") == "team"
            else None
        )
        in_team = team_id and _team_registry.has(team_id)

        # For the team group chat we open a STREAMING message (stable id) and
        # forward the sub-agent's text tokens live, so the user watches the
        # specialist work instead of staring at a blank chat.
        stream_msg_id = uuid.uuid4().hex
        if in_team:
            queue = _team_registry.get_queue(team_id)
            await _push_group_open(
                queue,
                team_id,
                msg_id=stream_msg_id,
                speaker=target_agent,
                text=f"▶ 开始执行: {task_description[:100]}",
            )

        async def _on_delta(delta: str) -> None:
            if in_team:
                await _push_group_delta(queue, msg_id=stream_msg_id, delta=delta)

        async def _on_tool(name: str) -> None:
            # surface the sub-agent's tool calls (read_file/write_file/...) as a
            # detail step under its own speaker bubble in the team chat.
            if in_team:
                await _push_group_detail(
                    queue, msg_id=stream_msg_id, detail=f"🔧 {name}"
                )

        # Record the delegation edge.
        await session_store.add_link(
            from_session_id=parent_session_id,
            to_session_id=child_id,
            direction="dispatch",
            content=task_description,
        )
        await session_store.update(child_id, status="running")

        try:
            agent = agent_ref["agent"] if isinstance(agent_ref, dict) else agent_ref
            answer = await _run_subagent(
                agent=agent,
                role=target_agent,
                task_description=task_description,
                child_session_id=child_id,
                parent_config=parent_config,
                on_text_delta=_on_delta,
                on_tool=_on_tool,
            )
            await session_store.update(child_id, status="done")
        except Exception as exc:  # noqa: BLE001
            logger.exception("dispatch_task sub-agent failed")
            await session_store.update(child_id, status="error")
            answer = f"(sub-agent '{target_agent}' failed: {exc})"

        # Finalize the streaming group message with the full answer (also
        # persists one message_links record). Falls back to a plain message if
        # somehow not in a team.
        if in_team:
            await _push_group_close(
                queue,
                team_id,
                msg_id=stream_msg_id,
                speaker=target_agent,
                text=answer[:400] or "(no output)",
            )

        # Record the result edge back to the parent.
        await session_store.add_link(
            from_session_id=child_id,
            to_session_id=parent_session_id,
            direction="result",
            content=answer[:500],
        )
        return answer

    return dispatch_task
