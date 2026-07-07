"""Agent configuration registry — now loaded from ~/.openmanus/agents/ (YAML).

The old hardcoded AGENT_CONFIGS dict is replaced by AgentLoader, which scans
the filesystem at startup. This module re-exports the loaded configs under the
same names (AGENT_CONFIGS, ROLES, role_prompt) so existing code keeps working
without changes.

To add a new agent: drop a directory with agent.yaml + prompt.md into
~/.openmanus/agents/ and restart.
"""

from __future__ import annotations

from typing import Any

from ..agent_loader import agent_loader

# These are populated at startup by main.py (which calls agent_loader.load_all()).
# Until then they're empty — code that needs them should call agent_loader directly.
AGENT_CONFIGS: dict[str, dict[str, Any]] = agent_loader.configs

# ROLES = dispatchable agents (everyone except the entry agent).
def _compute_roles() -> dict[str, dict[str, Any]]:
    return agent_loader.dispatchable()

# Backwards-compatible property-like access. Since AGENT_CONFIGS is a live ref
# to agent_loader.configs, it updates automatically after load_all().
ROLES = AGENT_CONFIGS  # alias; dispatchable filtering done at call sites


def role_prompt(role: str) -> str:
    """The system prompt for a role, or a sensible default."""
    cfg = agent_loader.get(role)
    if cfg:
        return cfg.get("prompt", "")
    return f"You are a {role} agent. Complete the task. Return a brief summary."
