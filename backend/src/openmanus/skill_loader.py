"""SkillLoader — scans ~/.openmanus/skills/ for SKILL.md files.

Each skill is a subdirectory containing a SKILL.md with YAML frontmatter:
  ---
  name: code_review
  description: Review code for best practices
  ---

The loader reads frontmatter (name + description) for the frontend listing.
The full SKILL.md content + supporting files (scripts/references/assets) are
read by the agent at runtime via the deepagents SkillsMiddleware (progressive
disclosure — agent reads SKILL.md on demand using read_file).

This loader is ONLY for listing/managing skills in the UI. The actual skill
loading at agent runtime is handled by the framework's SkillsMiddleware.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

OPENMANUS_HOME = Path(os.environ.get("OPENMANUS_HOME", Path.home() / ".openmanus"))
SKILLS_DIR = OPENMANUS_HOME / "skills"


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Extract YAML frontmatter from a SKILL.md file."""
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


class SkillLoader:
    """Loads skill metadata (name + description) from ~/.openmanus/skills/."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._dir = skills_dir or SKILLS_DIR
        self._skills: dict[str, dict[str, Any]] = {}

    @property
    def dir(self) -> Path:
        return self._dir

    def load_all(self) -> dict[str, dict[str, Any]]:
        """Scan skills directory, read each SKILL.md frontmatter."""
        self._skills.clear()
        if not self._dir.exists():
            logger.info("skills dir %s does not exist — no skills loaded", self._dir)
            return self._skills

        for entry in sorted(self._dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
                fm = _parse_frontmatter(content)
                name = fm.get("name", entry.name)
                description = fm.get("description", "")
                self._skills[name] = {
                    "name": name,
                    "description": description,
                    "dir": str(entry),
                    "has_scripts": (entry / "scripts").is_dir(),
                    "has_references": (entry / "references").is_dir(),
                }
                logger.info("loaded skill: %s", name)
            except Exception:  # noqa: BLE001
                logger.exception("failed to load skill from %s", entry)

        return self._skills

    def get(self, name: str) -> dict[str, Any] | None:
        return self._skills.get(name)

    def all_names(self) -> list[str]:
        return list(self._skills.keys())

    def skill_dir(self, name: str) -> Path | None:
        """Return the on-disk directory for a skill."""
        s = self._skills.get(name)
        return Path(s["dir"]) if s else None

    @property
    def skills(self) -> dict[str, dict[str, Any]]:
        return self._skills


# Module-level singleton.
skill_loader = SkillLoader()
