"""AgentLoader — loads agent definitions from ~/.openmanus/agents/ (YAML + prompt.md).

Each agent is a subdirectory containing:
  - agent.yaml : configuration (name, tools, flags, ...)
  - prompt.md  : system prompt (markdown, loaded as the system_prompt string)

On startup, main.py calls seed_builtin() (first-run only) then load_all().
The loaded configs replace the old hardcoded AGENT_CONFIGS dict.

This is the foundation for user-created agents: drop a new directory with an
agent.yaml + prompt.md into ~/.openmanus/agents/ and it becomes available.
"""

from __future__ import annotations

import logging
import os
import yaml
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Root for all user-configurable content.
OPENMANUS_HOME = Path(os.environ.get("OPENMANUS_HOME", Path.home() / ".openmanus"))
AGENTS_DIR = OPENMANUS_HOME / "agents"

# ─── builtin agent definitions (seeded on first run) ────────────────────────
# These are written to disk so users can inspect and modify them.

_BUILTIN_AGENTS: dict[str, dict[str, Any]] = {
    "manus": {
        "tools": ["dispatch"],
        "strip_file_tools": True,
        "allowed_tools": [],
        "prompt": """\
You are Manus, the entry routing agent. You have NO file tools. Your only job
is to decide, in ONE short sentence, who to delegate the user's request to,
then hand it off:

1. PURE CHAT / knowledge questions (greetings, "what is X"): answer directly
   from your own knowledge.

2. A SINGLE clear task ("implement X", "read Y", "investigate Z"): call
   `dispatch` with target_agent="coder" (changes) or "researcher" (read-only).

3. ANYTHING multi-step / needing coordination ("use a team", "research then
   build"): call `dispatch` with target_agent="teamleader".

CRITICAL: When you delegate, reply with ONE line (e.g. "Delegating to a
coder."). Do NOT restate the task, do NOT outline steps.
""",
    },
    "teamleader": {
        "tools": ["dispatch", "send_message", "read_mailbox",
                  "whiteboard_write", "whiteboard_read"],
        "strip_file_tools": False,
        "allowed_tools": [],
        "prompt": """\
You are a Team Leader. Your job is to DELEGATE work to specialist agents —
you do NOT do the work yourself.

Your specialists (via the `dispatch` tool):
- "researcher": read-only investigation (list/read/grep files).
- "coder": can read/write/edit/run files.

WORKFLOW:
1. Break the task into subtasks.
2. Call `dispatch` for EACH subtask. dispatch returns immediately — the agent
   runs in the background. You can dispatch multiple in one turn.
3. After dispatching ALL subtasks, STOP. Do NOT call read_mailbox — your inbox
   is empty right now because the agents are still working. Results will arrive
   AUTOMATICALLY in your next turn when agents finish. You do nothing in between.
4. When you receive results (they come to you automatically), review them. If
   follow-up work is needed, dispatch again. If everything is done, write a
   concise final summary.

CRITICAL: After dispatch, your reply should be ONE line (e.g. "Dispatched to
researcher and coder."). Then STOP. Do NOT call read_mailbox, do NOT poll,
do NOT call any other tool. Just stop and wait.
""",
    },
    "coder": {
        "tools": [],
        "strip_file_tools": False,
        "allowed_tools": ["read_file", "write_file", "edit_file",
                          "list_directory", "ls", "glob", "grep", "execute"],
        "prompt": """\
You are a coder agent. Implement the requested change in the codebase. You may
read, edit, write, and run files. Return a brief summary of what you changed.
""",
    },
    "researcher": {
        "tools": [],
        "strip_file_tools": False,
        "allowed_tools": ["read_file", "list_directory", "ls", "glob", "grep"],
        "prompt": """\
You are a researcher agent. Investigate the codebase to answer the task. You
may read, list, search, and grep files, but you CANNOT edit or execute
anything. Return a concise findings summary.
""",
    },
}


class AgentLoader:
    """Loads agent definitions from the filesystem (~/.openmanus/agents/)."""

    def __init__(self, agents_dir: Path | None = None) -> None:
        self._dir = agents_dir or AGENTS_DIR
        self._configs: dict[str, dict[str, Any]] = {}

    @property
    def dir(self) -> Path:
        return self._dir

    def seed_builtin(self) -> None:
        """Write builtin agent files to disk if they don't exist (first-run)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        for name, cfg in _BUILTIN_AGENTS.items():
            agent_dir = self._dir / name
            yaml_path = agent_dir / "agent.yaml"
            prompt_path = agent_dir / "prompt.md"
            if yaml_path.exists():
                continue  # don't overwrite user modifications
            agent_dir.mkdir(parents=True, exist_ok=True)
            # write prompt.md
            prompt_path.write_text(cfg["prompt"], encoding="utf-8")
            # write agent.yaml (without the prompt body — it's in prompt.md)
            yaml_data = {
                "name": name,
                "prompt_file": "prompt.md",
                "tools": cfg["tools"],
                "skills": [],
                "sub_agents": [],
                "strip_file_tools": cfg["strip_file_tools"],
                "allowed_tools": cfg["allowed_tools"],
            }
            yaml_path.write_text(
                yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
            logger.info("seeded builtin agent: %s", name)

    def load_all(self) -> dict[str, dict[str, Any]]:
        """Scan the agents directory and load every agent definition.

        Returns a dict keyed by agent name (lowercase). Each value has the
        same shape as the old AGENT_CONFIGS entries.
        """
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
                # load prompt from prompt_file
                prompt = ""
                prompt_file = raw.get("prompt_file", "prompt.md")
                prompt_path = entry / prompt_file
                if prompt_path.exists():
                    prompt = prompt_path.read_text(encoding="utf-8")
                # build the config entry (same shape as old AGENT_CONFIGS)
                cfg: dict[str, Any] = {
                    "prompt": prompt,
                    "tools": raw.get("tools", []),
                    "skills": raw.get("skills", []),
                    "sub_agents": raw.get("sub_agents", []),
                    "strip_file_tools": raw.get("strip_file_tools", False),
                    "allowed_tools": set(raw.get("allowed_tools", [])),
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

    def dispatchable(self) -> dict[str, dict[str, Any]]:
        """Agents that can be dispatched to (i.e. not the entry agent)."""
        return {
            k: v for k, v in self._configs.items()
        }

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
        return self._dir / name  # fallback

    def save_prompt(self, name: str, prompt: str) -> None:
        """Write the prompt body to the agent's prompt.md file."""
        d = self._agent_dir(name)
        yaml_path = d / "agent.yaml"
        prompt_file = "prompt.md"
        if yaml_path.exists():
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("prompt_file"):
                prompt_file = raw["prompt_file"]
        (d / prompt_file).write_text(prompt, encoding="utf-8")
        # update in-memory cache
        if name in self._configs:
            self._configs[name]["prompt"] = prompt

    def save_tools(self, name: str, tools: list[str]) -> None:
        """Write the tools list to the agent's agent.yaml file."""
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
        # update in-memory cache
        if name in self._configs:
            self._configs[name]["tools"] = tools

    def save_skills(self, name: str, skills: list[str]) -> None:
        """Write the skills list to the agent's agent.yaml file."""
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

    def create(self, name: str, prompt: str, tools: list[str]) -> dict:
        """Create a new agent on disk (directory + agent.yaml + prompt.md).

        Raises ValueError if the name already exists.
        """
        name = name.strip()
        if not name:
            raise ValueError("agent name cannot be empty")
        if name in self._configs:
            raise ValueError(f"agent '{name}' already exists")
        d = self._dir / name
        if d.exists():
            raise ValueError(f"directory '{d}' already exists")
        d.mkdir(parents=True, exist_ok=True)
        # write prompt.md
        (d / "prompt.md").write_text(prompt or "", encoding="utf-8")
        # write agent.yaml
        yaml_data = {
            "name": name,
            "prompt_file": "prompt.md",
            "tools": tools,
            "skills": [],
            "sub_agents": [],
            "strip_file_tools": False,
            "allowed_tools": [],
        }
        (d / "agent.yaml").write_text(
            yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        # add to in-memory cache
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
        """Delete an agent directory (not for built-in agents)."""
        if name in ("manus", "teamleader"):
            raise ValueError(f"cannot delete built-in agent '{name}'")
        cfg = self._configs.get(name)
        if not cfg:
            raise ValueError(f"agent '{name}' not found")
        d = self._agent_dir(name)
        if d.exists():
            import shutil
            shutil.rmtree(d)
        self._configs.pop(name, None)
        logger.info("deleted agent: %s", name)

    @property
    def configs(self) -> dict[str, dict[str, Any]]:
        return self._configs


# Module-level singleton.
agent_loader = AgentLoader()
