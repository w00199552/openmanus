"""AgentTrace middleware — logs every agent's model output + tool calls.

Mounts on every agent (manus / teamleader / coder / researcher) to make the
full message flow visible in the backend log. This is the debugging tool for
"why doesn't the frontend see coder's output" — you can trace exactly what each
agent produces and which tools it calls.

It prints:
  - after each model call: the agent name + the AI message text + tool calls
  - after each tool call: the tool name + a snippet of the result

No behaviour change — purely observational.
"""

from __future__ import annotations

import logging
from langchain.agents.middleware.types import AgentMiddleware
from typing import Any

logger = logging.getLogger("openmanus.trace")


def _short(text: Any, n: int = 120) -> str:
    s = str(text).replace("\n", " ").strip()
    return s[:n] + ("…" if len(s) > n else "")


class AgentTraceMiddleware(AgentMiddleware[Any, Any, Any]):
    """Logs model outputs + tool calls for tracing. Agent name from construction."""

    def __init__(self, *, name: str = "?") -> None:
        self._name = name

    async def awrap_model_call(self, request, handler):  # type: ignore[no-untyped-def]
        result = await handler(request)
        # result is a ModelResponse; extract the AI message to log it
        try:
            # The result carries choices / message — pull text + tool_calls
            msg = None
            if hasattr(result, "message"):
                msg = result.message
            elif hasattr(result, "choices") and result.choices:
                msg = result.choices[0].get("message") if isinstance(result.choices[0], dict) else None
            if msg is not None:
                # text content
                content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "")
                text = _short(content)
                # tool calls
                tcs = getattr(msg, "tool_calls", None) or (msg.get("tool_calls") if isinstance(msg, dict) else None)
                tc_names = [t.get("name", "?") if isinstance(t, dict) else getattr(t, "name", "?") for t in (tcs or [])]
                logger.warning("[TRACE] %s MODEL → text=%r tools=%s", self._name, text, tc_names)
            else:
                logger.warning("[TRACE] %s MODEL → (no message extracted)", self._name)
        except Exception:  # noqa: BLE001 — never break the agent for a log
            logger.warning("[TRACE] %s MODEL → (extract failed)", self._name)
        return result

    async def awrap_tool_call(self, request, handler):  # type: ignore[no-untyped-def]
        name = "?"
        tc = getattr(request, "tool_call", None)
        if isinstance(tc, dict):
            name = tc.get("name", "?")
        elif tc is not None:
            name = getattr(tc, "name", "?")
        result = await handler(request)
        try:
            content = getattr(result, "content", None) or ""
            logger.warning("[TRACE] %s TOOL %s → %s", self._name, name, _short(content))
        except Exception:  # noqa: BLE001
            logger.warning("[TRACE] %s TOOL %s → (done)", self._name, name)
        return result
