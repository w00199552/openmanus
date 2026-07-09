"""ToolGuardMiddleware — a HARD constraint that forbids an agent from using
certain tools.

Why this exists (not just _ToolExclusionMiddleware): deepagents'
``_ToolExclusionMiddleware`` only filters tools out of the *model request* (so
the model "doesn't see them"). But a model can still *hallucinate* a tool call
for a tool it was told about in the system prompt, and ``FilesystemMiddleware``
will happily execute it via its ``wrap_tool_call`` hook — bypassing the tools
list entirely. The net effect: the "excluded" tool still runs.

``ToolGuardMiddleware`` closes that hole with TWO layers:

1. ``awrap_model_call`` — strip the forbidden tools from the model request
   (same as _ToolExclusionMiddleware; keeps the tool list clean).
2. ``awrap_tool_call`` — if a forbidden tool is invoked anyway (hallucination),
   REJECT it with a short message instead of executing it.

Together they make the constraint physical: the agent cannot see the tools AND
cannot run them even if it tries.
"""

from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from typing import Any, Awaitable, Callable

if __name__ != "__main__":  # type guard for TYPE_CHECKING-only import
    pass


def _name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        n = tool.get("name")
        return n if isinstance(n, str) else None
    return getattr(tool, "name", None)


class ToolGuardMiddleware(AgentMiddleware[Any, Any, Any]):
    """Forbid a set of tools at both the model-request and tool-execution layers."""

    def __init__(self, *, excluded: frozenset[str]) -> None:
        self._excluded = excluded

    # --- layer 1: keep forbidden tools out of the model request -----------
    def wrap_model_call(self, request, handler):  # type: ignore[no-untyped-def]
        if self._excluded:
            request = request.override(
                tools=[t for t in request.tools if _name(t) not in self._excluded]
            )
        return handler(request)

    async def awrap_model_call(self, request, handler):  # type: ignore[no-untyped-def]
        if self._excluded:
            request = request.override(
                tools=[t for t in request.tools if _name(t) not in self._excluded]
            )
        return await handler(request)

    # --- layer 2: reject execution if a forbidden tool is called anyway ---
    def wrap_tool_call(self, request, handler):  # type: ignore[no-untyped-def]
        name = request.tool_call.get("name") if isinstance(request.tool_call, dict) else None
        if name in self._excluded:
            return ToolMessage(
                content=(
                    f"Tool '{name}' is not available to this agent. This is a "
                    f"router/read-only agent — delegate the work with "
                    f"dispatch_single / dispatch_to_team instead."
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=name or "blocked",
            )
        return handler(request)

    async def awrap_tool_call(self, request, handler):  # type: ignore[no-untyped-def]
        name = request.tool_call.get("name") if isinstance(request.tool_call, dict) else None
        if name in self._excluded:
            return ToolMessage(
                content=(
                    f"Tool '{name}' is not available to this agent. This is a "
                    f"router/read-only agent — delegate the work with "
                    f"dispatch_single / dispatch_to_team instead."
                ),
                tool_call_id=request.tool_call.get("id", ""),
                name=name or "blocked",
            )
        return await handler(request)
