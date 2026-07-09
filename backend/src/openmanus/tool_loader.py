"""ToolLoader — loads user-defined tools from ~/.openmanus/tools/.

Each tool is a subdirectory containing:
  - tool.yaml : metadata (name, entry, class, description)
  - entry.py  : the Python file with a BaseTool subclass (filename from yaml)

The tool.py file runs in the same .venv as the backend (full trust model,
like Claude Code plugins). The class specified in tool.yaml is instantiated
and registered by name.

Built-in tools (dispatch, send_message, read_mailbox, whiteboard_*, and
deepagents' filesystem tools) are NOT loaded here — they stay in code.

Usage in agent.yaml:
  tools:
    - dispatch              # built-in
    - search_testcase       # user-defined (from ~/.openmanus/tools/)
"""

from __future__ import annotations

import importlib.util
import logging
import os
import yaml
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OPENMANUS_HOME = Path(os.environ.get("OPENMANUS_HOME", Path.home() / ".openmanus"))
TOOLS_DIR = OPENMANUS_HOME / "tools"


class ToolLoader:
    """Loads user-defined tools from the filesystem."""

    def __init__(self, tools_dir: Path | None = None) -> None:
        self._dir = tools_dir or TOOLS_DIR
        self._tools: dict[str, Any] = {}  # name → BaseTool instance

    @property
    def dir(self) -> Path:
        return self._dir

    def load_all(self) -> dict[str, Any]:
        """Scan ~/.openmanus/tools/ and load every tool definition.

        Returns a dict of {name: BaseTool_instance}.
        """
        self._tools.clear()
        if not self._dir.exists():
            logger.info("tools dir %s does not exist — no user tools loaded", self._dir)
            return self._tools

        for entry in sorted(self._dir.iterdir()):
            if not entry.is_dir():
                continue
            yaml_path = entry / "tool.yaml"
            if not yaml_path.exists():
                continue
            try:
                self._load_one(entry, yaml_path)
            except Exception:  # noqa: BLE001
                logger.exception("failed to load tool from %s", entry)

        return self._tools

    def _load_one(self, tool_dir: Path, yaml_path: Path) -> None:
        """Load a single tool from its directory."""
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return

        name = raw.get("name") or tool_dir.name
        entry_file = raw.get("entry", "tool.py")
        class_name = raw.get("class", "")
        description = raw.get("description", "")

        if not class_name:
            logger.warning("tool %s: missing 'class' in tool.yaml, skipping", name)
            return

        # Strip .py suffix if present
        if entry_file.endswith(".py"):
            entry_file = entry_file[:-3]
        py_path = tool_dir / f"{entry_file}.py"
        if not py_path.exists():
            logger.warning("tool %s: entry file %s not found", name, py_path)
            return

        # Dynamic import
        module_name = f"openmanus_user_tool.{name}"
        spec = importlib.util.spec_from_file_location(module_name, str(py_path))
        if spec is None or spec.loader is None:
            logger.warning("tool %s: failed to create module spec", name)
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        tool_class = getattr(mod, class_name, None)
        if tool_class is None:
            logger.warning("tool %s: class %s not found in %s", name, class_name, py_path)
            return

        instance = tool_class()
        self._tools[name] = instance
        logger.info("loaded user tool: %s (class=%s from %s)", name, class_name, py_path.name)

    def get(self, name: str) -> Any | None:
        """Get a loaded tool instance by name."""
        return self._tools.get(name)

    def all_names(self) -> list[str]:
        return list(self._tools.keys())

    @property
    def tools(self) -> dict[str, Any]:
        return self._tools


# Module-level singleton.
tool_loader = ToolLoader()
