"""Mailbox tools — agent-to-agent peer messaging.

These are the COMMUNICATION tools: send_message / read_mailbox. They let agents
that are already running chat with each other (typically inside a team — e.g.
TeamLeader pinging a specialist, or two specialists coordinating).

This module is intentionally NARROW — it does NOT contain the dispatch tool.
Dispatch (creating a child session + starting it with a Task prompt) is a
separate control-flow concern, living in ``dispatch_tool.py``. The two used to
share this file, which caused a coupling bug: dispatch sent a mailbox message
that triggered _wakeup on the child and started a duplicate turn. They are now
split so each has a single responsibility.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_core.tools.base import InjectedToolArg
from pydantic import BaseModel, Field

from ..mailbox import mailbox_store

logger = logging.getLogger(__name__)


def _config_session_id(config: RunnableConfig | None) -> str:
    return ((config or {}).get("configurable") or {}).get("thread_id") or "unknown"


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
