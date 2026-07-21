"""Integration test: build_agent wires the tool whitelist into ToolGuardMiddleware.

This is the bridge test between Layer A (pure whitelist logic, covered in
test_tool_whitelist.py) and Layer C (ToolGuard behavior, covered in
test_tool_guard.py). It verifies that ``agent_factory.build_agent`` actually
passes the computed ``excluded`` set to a ToolGuardMiddleware instance during
real agent construction.

It does NOT call any LLM — the model factory is stubbed with a FakeModel
whose _generate raises if invoked (we only build, never stream). The
checkpointer is stubbed with an in-memory MemorySaver.

Run:  uv run pytest tests/test_build_agent_tools.py -v
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest.mock as mk
from pathlib import Path
from typing import Any

import pytest
import yaml

from openmanus import agent_factory as factory_mod
from openmanus.agent_factory import _BUILTIN_TOOLS, _resolve_tool_whitelist
from openmanus.middleware.tool_guard import ToolGuardMiddleware


# The exact `tools` lists from backend/seed/agents/*/agent.yaml.
SEED_TOOLS = {
    "Manus": ["dispatch"],
    "Coder": ["read_file", "write_file", "edit_file", "ls", "glob", "grep", "execute"],
    "Researcher": ["read_file", "ls", "glob", "grep"],
    "TeamLeader": [
        "dispatch", "send_message", "read_mailbox",
        "whiteboard_write", "whiteboard_read",
    ],
}

# (test session id, agent name) pairs the fakes below will resolve.
SESSION_FIXTURES = [
    ("s-manus", "Manus"),
    ("s-coder", "Coder"),
    ("s-researcher", "Researcher"),
    ("s-team", "TeamLeader"),
]


def _load_seed_configs() -> dict[str, dict[str, Any]]:
    """Read backend/seed/agents/* into in-memory configs (no disk copy)."""
    seed_dir = Path(__file__).resolve().parent.parent / "seed" / "agents"
    configs: dict[str, dict[str, Any]] = {}
    for agent_dir in sorted(seed_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        raw = yaml.safe_load((agent_dir / "agent.yaml").read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        prompt = ""
        pf = raw.get("prompt_file", "prompt.md")
        pp = agent_dir / pf
        if pp.exists():
            prompt = pp.read_text(encoding="utf-8")
        configs[raw.get("name") or agent_dir.name] = {
            "prompt": prompt,
            "description": raw.get("description", ""),
            "tools": raw.get("tools", []),
            "skills": raw.get("skills", []),
            "sub_agents": raw.get("sub_agents", []),
            "is_builtin": raw.get("is_builtin", False),
        }
    return configs


# ─── the integration test ──────────────────────────────────────────────────


def test_build_agent_wires_excluded_correctly():
    """build_agent must hand the whitelisted `excluded` to ToolGuardMiddleware.

    Strategy: spy on ToolGuardMiddleware.__init__ to capture the `excluded`
    arg for each agent build, then assert it matches the pure-function
    prediction (_resolve_tool_whitelist) for that agent's seed tools.
    """
    # Populate the global loader with seed configs.
    factory_mod.agent_loader._configs = _load_seed_configs()

    captured: list[frozenset[str]] = []
    real_init = ToolGuardMiddleware.__init__

    def spy_init(self, *, excluded):  # type: ignore[no-untyped-def]
        captured.append(frozenset(excluded))
        return real_init(self, excluded=excluded)

    # Stub the model so build_agent never needs a real LLM/API key.
    from langchain_core.language_models import BaseChatModel

    class _FakeModel(BaseChatModel):
        @property
        def _llm_type(self) -> str: return "fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            raise AssertionError("build should not invoke the model")

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            raise AssertionError("build should not invoke the model")

    from langgraph.checkpoint.memory import MemorySaver

    async def _fake_get_checkpointer() -> Any:
        return MemorySaver()

    tmp = tempfile.mkdtemp()
    session_map = {
        "s-manus": ("Manus", tmp),
        "s-coder": ("Coder", tmp),
        "s-researcher": ("Researcher", tmp),
        "s-team": ("TeamLeader", tmp),
    }

    async def _fake_session_get(sid: str) -> dict[str, Any] | None:
        if sid not in session_map:
            return None
        name, wd = session_map[sid]
        return {"name": name, "workdir": wd}

    spy_cls = type("SpyToolGuard", (ToolGuardMiddleware,), {"__init__": spy_init})
    original_cls = factory_mod.ToolGuardMiddleware
    original_model = factory_mod._default_model
    factory_mod.ToolGuardMiddleware = spy_cls  # type: ignore[misc]
    factory_mod._default_model = _FakeModel()  # type: ignore[attr-defined]

    guards: dict[str, frozenset[str]] = {}
    try:
        with mk.patch.object(factory_mod, "get_checkpointer", side_effect=_fake_get_checkpointer), \
             mk.patch.object(factory_mod, "session_store") as sess_mock:
            sess_mock.get = _fake_session_get

            for sid, agent_name in SESSION_FIXTURES:
                captured.clear()
                agent = asyncio.run(factory_mod.build_agent(sid))
                assert captured, f"ToolGuardMiddleware was not constructed for {agent_name}"
                guards[agent_name] = captured[0]
                asyncio.run(factory_mod.close_agent(agent))
    finally:
        factory_mod.ToolGuardMiddleware = original_cls  # type: ignore[misc]
        factory_mod._default_model = original_model

    # Each agent's guard must match the pure-function prediction exactly.
    for name, tools in SEED_TOOLS.items():
        _kept, expected_excluded, _ = _resolve_tool_whitelist(tools)
        actual = guards[name]
        assert actual == expected_excluded, (
            f"{name}: guard excluded={sorted(actual)} != expected={sorted(expected_excluded)}"
        )


@pytest.mark.parametrize("agent_name", list(SEED_TOOLS))
def test_seed_tools_cover_only_known_categories(agent_name):
    """Every tool name in a seed agent must be either a deepagents builtin
    or a known OpenManus builtin. Catches typos in seed/agents/*.yaml.

    OpenManus builtins: dispatch / send_message / read_mailbox /
    whiteboard_write / whiteboard_read.
    """
    openmanus_builtins = {
        "dispatch", "send_message", "read_mailbox",
        "whiteboard_write", "whiteboard_read",
    }
    for tname in SEED_TOOLS[agent_name]:
        is_deepagents = tname in _BUILTIN_TOOLS
        is_openmanus = tname in openmanus_builtins
        assert is_deepagents or is_openmanus, (
            f"{agent_name}.tools contains unknown tool {tname!r} — "
            f"not a deepagents builtin nor an OpenManus builtin. Typo?"
        )
