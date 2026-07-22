"""Mailbox tools — agent-to-agent peer messaging.

These are the COMMUNICATION tools: send_message / read_mailbox. They let
agents that are already running chat with each other (typically inside a
team — e.g. TeamLeader pinging a specialist, or two specialists
coordinating).

Messages are topic-scoped and addressed by **agent name**, not session id:
the tools read ``agent_name`` and ``topic_id`` from the running agent's
``RunnableConfig`` and pass them straight through to ``mailbox_store``.

This module is intentionally NARROW — it does NOT contain the dispatch tool.
Dispatch (creating a child session + starting it with a Task prompt) is a
separate control-flow concern, living in ``dispatch_tool.py``. The two used
to share this file, which caused a coupling bug: dispatch sent a mailbox
message that triggered the wake-up callback on the child and started a
duplicate turn. They are now split so each has a single responsibility.
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


def _config_agent_name(config: RunnableConfig | None) -> str:
    return ((config or {}).get("configurable") or {}).get("agent_name") or "unknown"


def _config_topic_id(config: RunnableConfig | None) -> str:
    tid = ((config or {}).get("configurable") or {}).get("topic_id")
    return tid or "main"


def make_send_message_tool() -> BaseTool:
    class SendMessageInput(BaseModel):
        to_agent: str = Field(description="Name of the agent to message.")
        content: str = Field(description="The message text.")

    @tool("send_message", args_schema=SendMessageInput)
    async def send_message(
        to_agent: str,
        content: str,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Send a short chat message to another agent in your team."""
        await mailbox_store.send(
            topic_id=_config_topic_id(config),
            from_agent=_config_agent_name(config),
            to_agent=to_agent,
            kind="chat",
            content=content,
        )
        return f"Sent message to {to_agent}."

    return send_message


def make_read_mailbox_tool() -> BaseTool:
    @tool("read_mailbox")
    async def read_mailbox(
        unread_only: bool = False,
        config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
    ) -> str:
        """Read messages in your inbox (tasks, peer chat, results)."""
        msgs = await mailbox_store.inbox(
            _config_topic_id(config), _config_agent_name(config), unread_only=unread_only
        )
        if not msgs:
            return "Inbox empty."
        lines = []
        for m in msgs:
            tail = m.get("content") or ""
            if m.get("whiteboard_ref"):
                tail += f" (whiteboard: {m['whiteboard_ref']})"
            lines.append(f"[{m['kind']}] from {m.get('from_agent')}: {tail}")
        return "Inbox:\n" + "\n".join(lines)

    return read_mailbox
