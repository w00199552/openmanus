"""Layer A — tool whitelist partitioning (agent_factory._resolve_tool_whitelist).

This is the core logic that decides, given an agent's declared `tools` list,
which deepagents builtins to keep / exclude / treat as extras. The integration
with build_agent is covered in test_build_agent_tools.py; here we focus on the
pure-function edge cases and partition invariants.

Run:  uv run pytest tests/test_tool_whitelist.py -v
"""

from __future__ import annotations

import pytest

from openmanus.agent_factory import _BUILTIN_TOOLS, _resolve_tool_whitelist


# ─── the four seed agents (kept in sync with seed/agents/*/agent.yaml) ───────

SEED_TOOLS = {
    "Manus": ["dispatch"],
    "Coder": ["read_file", "write_file", "edit_file", "ls", "glob", "grep", "execute"],
    "Researcher": ["read_file", "ls", "glob", "grep"],
    "TeamLeader": [
        "dispatch", "send_message", "read_mailbox",
        "whiteboard_write", "whiteboard_read",
    ],
}

# Tool names a read-only agent must NEVER be able to call.
WRITE_EXEC_TOOLS = ["write_file", "edit_file", "execute", "task", "write_todos"]


# ─── per-agent role boundaries ──────────────────────────────────────────────


class TestSeedAgentBoundaries:
    """Each built-in agent must enforce its intended tool boundary."""

    @pytest.mark.parametrize("agent_name", list(SEED_TOOLS))
    def test_partition_is_exhaustive_and_disjoint(self, agent_name):
        """Invariant: kept | excluded == _BUILTIN_TOOLS, kept & excluded == ∅."""
        kept, excluded, _ = _resolve_tool_whitelist(SEED_TOOLS[agent_name])
        assert kept | excluded == _BUILTIN_TOOLS
        assert kept & excluded == frozenset()

    def test_researcher_is_read_only(self):
        """Researcher must exclude every write/exec/todo/subagent tool."""
        kept, excluded, _ = _resolve_tool_whitelist(SEED_TOOLS["Researcher"])
        for forbidden in WRITE_EXEC_TOOLS:
            assert forbidden in excluded, (
                f"Researcher should exclude {forbidden}; excluded={sorted(excluded)}"
            )
        # and the read tools it DOES want are kept
        for required in ("read_file", "ls", "glob", "grep"):
            assert required in kept

    def test_coder_has_write_execute_but_no_task(self):
        """Coder keeps write/edit/execute but excludes task (no sub-agent yet)."""
        kept, excluded, _ = _resolve_tool_whitelist(SEED_TOOLS["Coder"])
        for required in ("read_file", "write_file", "edit_file", "execute", "ls", "glob", "grep"):
            assert required in kept
        assert "task" in excluded
        assert "write_todos" in excluded

    def test_manus_keeps_no_builtins(self):
        """Manus is a pure router: zero builtins kept, dispatch as extra."""
        kept, excluded, extras = _resolve_tool_whitelist(SEED_TOOLS["Manus"])
        assert kept == frozenset()
        assert excluded == _BUILTIN_TOOLS
        assert extras == ["dispatch"]

    def test_teamleader_keeps_no_builtins(self):
        """TeamLeader coordinates only: zero builtins, mailbox/whiteboard extras."""
        kept, excluded, extras = _resolve_tool_whitelist(SEED_TOOLS["TeamLeader"])
        assert kept == frozenset()
        assert excluded == _BUILTIN_TOOLS
        assert extras == sorted(SEED_TOOLS["TeamLeader"])


# ─── pure-function edge cases ───────────────────────────────────────────────


class TestWhitelistEdgeCases:
    """Edge cases that don't correspond to a specific agent."""

    def test_empty_whitelist_excludes_every_builtin(self):
        """An agent declaring no tools gets every builtin excluded."""
        kept, excluded, extras = _resolve_tool_whitelist([])
        assert kept == frozenset()
        assert excluded == _BUILTIN_TOOLS
        assert extras == []

    def test_all_builtins_whitelisted_excludes_none(self):
        """An agent listing every builtin keeps them all, excludes nothing."""
        all_builtins = list(_BUILTIN_TOOLS)
        kept, excluded, extras = _resolve_tool_whitelist(all_builtins)
        assert kept == _BUILTIN_TOOLS
        assert excluded == frozenset()
        assert extras == []

    def test_only_extras_no_builtins(self):
        """Non-builtin names go to extras, every builtin excluded."""
        kept, excluded, extras = _resolve_tool_whitelist(["dispatch", "send_message"])
        assert kept == frozenset()
        assert excluded == _BUILTIN_TOOLS
        assert extras == ["dispatch", "send_message"]

    def test_mixed_builtins_and_extras(self):
        """Mix: some builtins kept, rest excluded, extras carry the non-builtins."""
        kept, excluded, extras = _resolve_tool_whitelist(
            ["read_file", "execute", "dispatch", "whiteboard_read"]
        )
        assert kept == frozenset({"read_file", "execute"})
        # everything else in _BUILTIN_TOOLS is excluded
        assert excluded == (_BUILTIN_TOOLS - {"read_file", "execute"})
        # extras are sorted, non-builtin
        assert extras == ["dispatch", "whiteboard_read"]

    def test_unknown_builtin_silently_treated_as_extra(self):
        """A misspelled builtin name is NOT in _BUILTIN_TOOLS, so it lands in extras.

        This documents current behavior: unknown names don't error, they just
        become extras (which _build_tools will then warn about and skip).
        """
        kept, excluded, extras = _resolve_tool_whitelist(["read_file", "readfile_typo"])
        assert kept == frozenset({"read_file"})
        assert "readfile_typo" in extras

    def test_accepts_set_input(self):
        """The function must accept a set, not just a list."""
        kept_list, _, _ = _resolve_tool_whitelist(["read_file", "execute"])
        kept_set, _, _ = _resolve_tool_whitelist({"read_file", "execute"})
        assert kept_list == kept_set

    def test_duplicates_collapse(self):
        """Duplicate names in the input must not break the partition."""
        kept, excluded, _ = _resolve_tool_whitelist(["read_file", "read_file", "read_file"])
        assert kept == frozenset({"read_file"})
        assert excluded == _BUILTIN_TOOLS - {"read_file"}

    def test_returns_frozensets_for_immutability(self):
        """kept/excluded must be frozenset (immutable) so callers can't mutate them."""
        kept, excluded, _ = _resolve_tool_whitelist(["read_file"])
        assert isinstance(kept, frozenset)
        assert isinstance(excluded, frozenset)

    def test_extras_returned_sorted(self):
        """extras must be sorted for deterministic _build_tools iteration."""
        _, _, extras = _resolve_tool_whitelist(["zebra_tool", "alpha_tool", "read_file"])
        assert extras == sorted(["zebra_tool", "alpha_tool"])
