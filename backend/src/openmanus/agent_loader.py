"""AgentLoader — loads agent definitions from ~/.openmanus/agents/ (YAML + prompt.md).

Each agent is a subdirectory containing:
  - agent.yaml : configuration (name, tools, flags, ...)
  - prompt.md  : system prompt (markdown, loaded as the system_prompt string)

On startup, main.py calls seed_builtin() (first-run only) then load_all().
seed_builtin() copies the seed/agents/ directory (bundled with the app) to
~/.openmanus/agents/ if it doesn't exist yet.

This is the foundation for user-created agents: drop a new directory with an
agent.yaml + prompt.md into ~/.openmanus/agents/ and it becomes available.
"""

from __future__ import annotations

import logging
import os
import shutil
import yaml
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Root for all user-configurable content.
OPENMANUS_HOME = Path(os.environ.get("OPENMANUS_HOME", Path.home() / ".openmanus"))
AGENTS_DIR = OPENMANUS_HOME / "agents"

# Seed directory: bundled with the app (backend/seed/agents/).
# PyInstaller: --add-data seed/agents;seed/agents
_SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seed" / "agents"


class AgentLoader:
    """Loads agent definitions from the filesystem (~/.openmanus/agents/)."""

    def __init__(self, agents_dir: Path | None = None) -> None:
        self._dir = agents_dir or AGENTS_DIR
        self._configs: dict[str, dict[str, Any]] = {}

    @property
    def dir(self) -> Path:
        return self._dir

    def seed_builtin(self) -> None:
        """Copy seed/agents/ to ~/.openmanus/agents/ on first run.

        Does NOT overwrite existing agents (user modifications are preserved).
        """
        if not _SEED_DIR.exists():
            logger.warning("seed dir %s not found — skipping seed", _SEED_DIR)
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        for entry in sorted(_SEED_DIR.iterdir()):
            if not entry.is_dir():
                continue
            target = self._dir / entry.name
            if target.exists():
                continue  # don't overwrite user modifications
            shutil.copytree(entry, target)
            logger.info("seeded agent: %s", entry.name)

    def load_all(self) -> dict[str, dict[str, Any]]:
        """Scan the agents directory and load every agent definition."""
        self._configs.clear()
        if not self._dir.exists():
            logger.warning("agents dir %s does not exist — no agents loaded", self._dir)
            return self._configs

        for entry in sorted(self._dir.iterdir()):
            if not entry.is_dir():
                continue
            yaml_path = entry / "agent.yaml"
            if not yaml_path.exists():
                continue
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    continue
                name = raw.get("name") or entry.name
                prompt = ""
                prompt_file = raw.get("prompt_file", "prompt.md")
                prompt_path = entry / prompt_file
                if prompt_path.exists():
                    prompt = prompt_path.read_text(encoding="utf-8")
                cfg: dict[str, Any] = {
                    "prompt": prompt,
                    "description": raw.get("description", ""),
                    "tools": raw.get("tools", []),
                    "skills": raw.get("skills", []),
                    "sub_agents": raw.get("sub_agents", []),
                    "strip_file_tools": raw.get("strip_file_tools", False),
                    "allowed_tools": set(raw.get("allowed_tools", [])),
                    "is_builtin": raw.get("is_builtin", False),
                }
                self._configs[name] = cfg
                logger.info("loaded agent: %s (tools=%s)", name, cfg["tools"])
            except Exception:  # noqa: BLE001
                logger.exception("failed to load agent from %s", entry)

        return self._configs

    def get(self, name: str) -> dict[str, Any] | None:
        """Case-insensitive lookup."""
        return self._configs.get(name) or self._configs.get(name.lower())

    def all_names(self) -> list[str]:
        return list(self._configs.keys())

    def _agent_dir(self, name: str) -> Path:
        """Find the on-disk directory for an agent (by name)."""
        for entry in self._dir.iterdir():
            if not entry.is_dir():
                continue
            yaml_path = entry / "agent.yaml"
            if not yaml_path.exists():
                continue
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and (raw.get("name") or entry.name).lower() == name.lower():
                return entry
            if entry.name.lower() == name.lower():
                return entry
        return self._dir / name

    def save_prompt(self, name: str, prompt: str) -> None:
        d = self._agent_dir(name)
        yaml_path = d / "agent.yaml"
        prompt_file = "prompt.md"
        if yaml_path.exists():
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("prompt_file"):
                prompt_file = raw["prompt_file"]
        (d / prompt_file).write_text(prompt, encoding="utf-8")
        if name in self._configs:
            self._configs[name]["prompt"] = prompt

    def save_tools(self, name: str, tools: list[str]) -> None:
        d = self._agent_dir(name)
        yaml_path = d / "agent.yaml"
        if not yaml_path.exists():
            return
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        raw["tools"] = tools
        yaml_path.write_text(
            yaml.dump(raw, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        if name in self._configs:
            self._configs[name]["tools"] = tools

    def save_skills(self, name: str, skills: list[str]) -> None:
        d = self._agent_dir(name)
        yaml_path = d / "agent.yaml"
        if not yaml_path.exists():
            return
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        raw["skills"] = skills
        yaml_path.write_text(
            yaml.dump(raw, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        if name in self._configs:
            self._configs[name]["skills"] = skills

    def save_description(self, name: str, description: str) -> None:
        """Write the description to the agent's agent.yaml file."""
        d = self._agent_dir(name)
        yaml_path = d / "agent.yaml"
        if not yaml_path.exists():
            return
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        raw["description"] = description
        yaml_path.write_text(
            yaml.dump(raw, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        if name in self._configs:
            self._configs[name]["description"] = description

    def create(self, name: str, prompt: str, tools: list[str], description: str = "") -> dict:
        name = name.strip()
        if not name:
            raise ValueError("agent name cannot be empty")
        if name in self._configs:
            raise ValueError(f"agent '{name}' already exists")
        d = self._dir / name
        if d.exists():
            raise ValueError(f"directory '{d}' already exists")
        d.mkdir(parents=True, exist_ok=True)
        (d / "prompt.md").write_text(prompt or "", encoding="utf-8")
        yaml_data = {
            "name": name,
            "description": description,
            "prompt_file": "prompt.md",
            "tools": tools,
            "skills": [],
            "sub_agents": [],
            "strip_file_tools": False,
            "allowed_tools": [],
            "is_builtin": False,
        }
        (d / "agent.yaml").write_text(
            yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        self._configs[name] = {
            "prompt": prompt or "",
            "tools": tools,
            "skills": [],
            "sub_agents": [],
            "strip_file_tools": False,
            "allowed_tools": set(),
        }
        logger.info("created agent: %s", name)
        return self._configs[name]

    def delete(self, name: str) -> None:
        cfg = self._configs.get(name)
        if not cfg:
            raise ValueError(f"agent '{name}' not found")
        if cfg.get("is_builtin", False):
            raise ValueError(f"cannot delete built-in agent '{name}'")
        cfg = self._configs.get(name)
        if not cfg:
            raise ValueError(f"agent '{name}' not found")
        d = self._agent_dir(name)
        if d.exists():
            shutil.rmtree(d)
        self._configs.pop(name, None)
        logger.info("deleted agent: %s", name)

    @property
    def configs(self) -> dict[str, dict[str, Any]]:
        return self._configs


# Module-level singleton.
agent_loader = AgentLoader()
