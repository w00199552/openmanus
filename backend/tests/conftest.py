"""Shared pytest fixtures for the OpenManus backend test suite.

Key fixtures:
  * ``tmp_openmanus_home`` — isolates ``~/.openmanus`` to a temp dir so tests
    never touch the real user config (``~/.openmanus/agents`` / ``tools`` /
    ``skills``). Sets the ``OPENMANUS_HOME`` env var, which ``agent_loader``
    and ``tool_loader`` read at import time via ``Path(os.environ[...])``.
  * ``seed_agents_in_loader`` — populates the in-memory ``agent_loader`` with
    the four built-in agents read from ``backend/seed/agents/``, without
    copying anything to disk.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml


# ─── path helpers ───────────────────────────────────────────────────────────

BACKEND_ROOT = Path(__file__).resolve().parent.parent
SEED_AGENTS_DIR = BACKEND_ROOT / "seed" / "agents"


def _read_seed_agents() -> dict[str, dict[str, Any]]:
    """Read backend/seed/agents/*/agent.yaml + prompt.md into in-memory configs.

    Mirrors what ``AgentLoader.load_all`` would produce if the seed had been
    copied to ``~/.openmanus/agents/``, but without touching the filesystem.
    """
    configs: dict[str, dict[str, Any]] = {}
    for agent_dir in sorted(SEED_AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        yaml_path = agent_dir / "agent.yaml"
        if not yaml_path.exists():
            continue
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        prompt = ""
        pf = raw.get("prompt_file", "prompt.md")
        pp = agent_dir / pf
        if pp.exists():
            prompt = pp.read_text(encoding="utf-8")
        name = raw.get("name") or agent_dir.name
        configs[name] = {
            "prompt": prompt,
            "description": raw.get("description", ""),
            "tools": raw.get("tools", []),
            "skills": raw.get("skills", []),
            "sub_agents": raw.get("sub_agents", []),
            "is_builtin": raw.get("is_builtin", False),
        }
    return configs


# ─── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_openmanus_home(tmp_path, monkeypatch):
    """Point OPENMANUS_HOME at a temp dir for the duration of the test.

    ``agent_loader`` / ``tool_loader`` read OPENMANUS_HOME at module-import
    time into module-level constants (``OPENMANUS_HOME`` / ``AGENTS_DIR`` /
    ``TOOLS_DIR``). For tests that construct their OWN loader instance with an
    explicit dir, this fixture mainly keeps the env var clean so the module
    singletons don't accidentally hit the real home.

    Returns the temp dir Path. The dir already contains empty ``agents`` /
    ``tools`` / ``skills`` subdirs so loaders find a well-formed layout.
    """
    home = tmp_path / "openmanus_home"
    (home / "agents").mkdir(parents=True)
    (home / "tools").mkdir(parents=True)
    (home / "skills").mkdir(parents=True)
    monkeypatch.setenv("OPENMANUS_HOME", str(home))
    return home


@pytest.fixture
def seed_agents_in_loader():
    """Populate the global agent_loader singleton with the four seed agents.

    Writes into ``agent_loader._configs`` directly (the same dict ``load_all``
    fills). Cleans up by restoring the previous state after the test so tests
    don't leak agent definitions into each other.
    """
    from openmanus.agent_loader import agent_loader

    saved = dict(agent_loader._configs)
    agent_loader._configs = _read_seed_agents()
    try:
        yield agent_loader
    finally:
        agent_loader._configs = saved
