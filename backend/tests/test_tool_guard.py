"""Layer C — ToolGuardMiddleware double-layer interception.

ToolGuard enforces tool exclusion at TWO layers (see middleware/tool_guard.py
docstring):
  1. ``wrap_model_call`` — strip excluded tools from the model request so the
     LLM never even sees them.
  2. ``wrap_tool_call`` — if the model hallucinates a call to an excluded tool
     anyway, reject it with a ToolMessage instead of executing it.

Layer 2 is the crucial defense: deepagents' own ``_ToolExclusionMiddleware``
only does layer 1, so a hallucinated tool call would still execute. ToolGuard
closes that hole.

Tests use minimal fake request objects — they expose only the attributes
ToolGuard actually touches (``.tools``, ``.override()``, ``.tool_call``).
This keeps the test focused on ToolGuard's own logic, not on langchain's
ModelRequest internals.

Run:  uv run pytest tests/test_tool_guard.py -v
"""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage

from openmanus.middleware.tool_guard import ToolGuardMiddleware


# ─── fake request objects (minimal surface ToolGuard touches) ───────────────


class FakeModelRequest:
    """Minimal stand-in for langchain's ModelRequest.

    ToolGuard reads ``.tools`` and calls ``.override(tools=...)``. We capture
    the override instead of returning a real ModelRequest — what matters is
    that the filtered tool list was computed and passed through.
    """

    def __init__(self, tools):
        # Tools may be BaseTool instances (have .name) or dicts (have ["name"]).
        self.tools = tools
        self.overridden_with = None

    def override(self, **kw):
        # Return a new FakeModelRequest carrying the override, so the test can
        # inspect what the handler actually received.
        self.overridden_with = kw
        new = FakeModelRequest(kw.get("tools", self.tools))
        return new


class FakeToolCallRequest:
    """Minimal stand-in for the tool-call request ToolGuard sees.

    ``request.tool_call`` is a dict with at least ``name`` and ``id``.
    """

    def __init__(self, name: str, call_id: str = "tc1"):
        self.tool_call = {"name": name, "id": call_id}


def _fake_tool(name: str):
    """A tiny object with a .name attribute, like a BaseTool."""
    class _T:
        pass
    t = _T()
    t.name = name
    return t


def _dict_tool(name: str) -> dict:
    """A dict-shaped tool, which is how some middleware inject tools."""
    return {"name": name, "description": f"fake {name}"}


# ─── shared fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def guard_with_excludes():
    """A ToolGuard excluding the file tools a Researcher should never have."""
    return ToolGuardMiddleware(
        excluded=frozenset({"write_file", "edit_file", "execute", "task", "write_todos"})
    )


@pytest.fixture
def guard_empty():
    """A ToolGuard with no exclusions — should be a no-op passthrough."""
    return ToolGuardMiddleware(excluded=frozenset())


# ─── layer 1: wrap_model_call (request-side filtering) ─────────────────────


class TestModelCallFiltering:
    """Layer 1: excluded tools must be stripped from the request.tools."""

    def test_excluded_tools_are_stripped_from_request(self, guard_with_excludes):
        req = FakeModelRequest([_fake_tool("read_file"), _fake_tool("write_file"), _fake_tool("ls")])
        captured = []

        def handler(r):
            captured.append(r)
            return "ok"

        guard_with_excludes.wrap_model_call(req, handler)
        # The handler received the filtered request
        assert len(captured) == 1
        passed_tools = captured[0].tools
        passed_names = {t.name for t in passed_tools}
        assert passed_names == {"read_file", "ls"}
        assert "write_file" not in passed_names

    def test_dict_shaped_tools_are_also_filtered(self, guard_with_excludes):
        """Tools may arrive as dicts (with a 'name' key) — those must filter too."""
        req = FakeModelRequest([_dict_tool("read_file"), _dict_tool("execute"), _dict_tool("grep")])
        captured = []
        guard_with_excludes.wrap_model_call(req, lambda r: captured.append(r))
        passed_names = {t["name"] for t in captured[0].tools}
        assert passed_names == {"read_file", "grep"}

    def test_no_exclusions_passes_all_tools(self, guard_empty):
        """An empty excluded set is a passthrough — no tools removed."""
        tools = [_fake_tool("read_file"), _fake_tool("write_file")]
        req = FakeModelRequest(tools)
        captured = []
        guard_empty.wrap_model_call(req, lambda r: captured.append(r))
        assert captured[0].tools == tools  # identity, no override happened

    def test_handler_return_value_is_passed_through(self, guard_with_excludes):
        """The handler's return value must come back unchanged."""
        req = FakeModelRequest([_fake_tool("read_file")])
        result = guard_with_excludes.wrap_model_call(req, lambda r: "the-result")
        assert result == "the-result"

    def test_request_with_only_excluded_tools_becomes_empty(self, guard_with_excludes):
        """If every tool is excluded, the handler sees an empty tool list."""
        req = FakeModelRequest([_fake_tool("write_file"), _fake_tool("execute")])
        captured = []
        guard_with_excludes.wrap_model_call(req, lambda r: captured.append(r))
        assert captured[0].tools == []


# ─── layer 1 async variant ──────────────────────────────────────────────────


class TestModelCallFilteringAsync:
    """awrap_model_call must behave identically to the sync version."""

    async def test_async_strips_excluded_tools(self, guard_with_excludes):
        req = FakeModelRequest([_fake_tool("read_file"), _fake_tool("write_file")])
        captured = []

        async def handler(r):
            captured.append(r)
            return "ok"

        await guard_with_excludes.awrap_model_call(req, handler)
        passed_names = {t.name for t in captured[0].tools}
        assert passed_names == {"read_file"}

    async def test_async_no_exclusions_passthrough(self, guard_empty):
        req = FakeModelRequest([_fake_tool("read_file")])

        async def handler(r):
            return "passthrough"

        result = await guard_empty.awrap_model_call(req, handler)
        assert result == "passthrough"


# ─── layer 2: wrap_tool_call (execution-side rejection) ────────────────────


class TestToolCallRejection:
    """Layer 2: a hallucinated call to an excluded tool must be REJECTED.

    The handler must NOT run; instead a ToolMessage explains the rejection.
    This is the layer that distinguishes ToolGuard from the framework's own
    _ToolExclusionMiddleware (which only does layer 1).
    """

    def test_excluded_tool_call_returns_toolmessage_not_handler(self, guard_with_excludes):
        req = FakeToolCallRequest("write_file")
        handler_called = []

        def handler(r):
            handler_called.append(r)
            return "should-not-reach"

        result = guard_with_excludes.wrap_tool_call(req, handler)
        assert isinstance(result, ToolMessage)
        assert handler_called == [], "handler must NOT be invoked for excluded tools"
        # content should mention the tool name and explain why
        assert "write_file" in result.content
        assert "not available" in result.content.lower()

    def test_allowed_tool_call_invokes_handler(self, guard_with_excludes):
        req = FakeToolCallRequest("read_file")
        handler_called = []

        def handler(r):
            handler_called.append(r)
            return "ran-read-file"

        result = guard_with_excludes.wrap_tool_call(req, handler)
        assert result == "ran-read-file"
        assert len(handler_called) == 1

    def test_rejected_message_carries_correct_tool_call_id(self, guard_with_excludes):
        """The ToolMessage's tool_call_id must match the request's, so the
        conversation graph can pair the rejection with the originating call."""
        req = FakeToolCallRequest("execute", call_id="call-xyz-123")
        result = guard_with_excludes.wrap_tool_call(req, lambda r: None)
        assert isinstance(result, ToolMessage)
        assert result.tool_call_id == "call-xyz-123"

    def test_rejected_message_name_is_the_blocked_tool(self, guard_with_excludes):
        req = FakeToolCallRequest("edit_file")
        result = guard_with_excludes.wrap_tool_call(req, lambda r: None)
        assert result.name == "edit_file"

    def test_empty_excluded_set_lets_everything_through(self, guard_empty):
        """With no exclusions, every tool call reaches the handler."""
        req = FakeToolCallRequest("write_file")
        result = guard_empty.wrap_tool_call(req, lambda r: "executed")
        assert result == "executed"


# ─── layer 2 async variant ──────────────────────────────────────────────────


class TestToolCallRejectionAsync:
    async def test_async_rejects_excluded_tool(self, guard_with_excludes):
        req = FakeToolCallRequest("write_file")
        handler_called = []

        async def handler(r):
            handler_called.append(r)
            return "should-not-reach"

        result = await guard_with_excludes.awrap_tool_call(req, handler)
        assert isinstance(result, ToolMessage)
        assert handler_called == []

    async def test_async_allows_approved_tool(self, guard_with_excludes):
        req = FakeToolCallRequest("read_file")

        async def handler(r):
            return "ran"

        result = await guard_with_excludes.awrap_tool_call(req, handler)
        assert result == "ran"


# ─── combined behavior: the two layers together ────────────────────────────


class TestLayeredDefense:
    """The point of ToolGuard is that BOTH layers fire together.

    Even if layer 1 somehow failed (e.g. a tool leaked into the request),
    layer 2 still blocks execution. This is why we keep ToolGuard even though
    deepagents' own _ToolExclusionMiddleware also does layer-1 filtering.
    """

    def test_researcher_cannot_write_even_if_request_leaked_it(self):
        """Simulate layer-1 failure: write_file is in the request. Layer 2
        must still reject the call."""
        guard = ToolGuardMiddleware(
            excluded=frozenset({"write_file", "edit_file", "execute"})
        )
        # layer 1 would have stripped write_file, but pretend it didn't:
        req = FakeToolCallRequest("write_file")
        result = guard.wrap_tool_call(req, lambda r: "wrote!")
        assert isinstance(result, ToolMessage)
        assert "wrote!" != result  # handler did not run

    def test_manus_router_pattern_blocks_all_file_tools(self):
        """Manus (pure router) excludes every file tool — verify the pattern
        end-to-end at both layers."""
        from openmanus.agent_factory import _BUILTIN_TOOLS
        # Manus excludes every builtin; its only extra is 'dispatch' (non-builtin).
        guard = ToolGuardMiddleware(excluded=_BUILTIN_TOOLS)

        # layer 1: all builtins stripped from request
        req = FakeModelRequest([_fake_tool(n) for n in ["read_file", "write_file", "execute"]])
        captured = []
        guard.wrap_model_call(req, lambda r: captured.append(r))
        assert captured[0].tools == []

        # layer 2: even if a file tool call slipped through, it's rejected
        for forbidden in ["read_file", "write_file", "execute"]:
            r = guard.wrap_tool_call(FakeToolCallRequest(forbidden), lambda r: None)
            assert isinstance(r, ToolMessage), f"{forbidden} should be blocked"
