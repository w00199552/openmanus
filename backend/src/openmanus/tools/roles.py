"""Agent configuration registry.

All agents (manus / teamleader / coder / researcher) are defined here as
configurations. They are EQUAL — each is an independent agent created fresh by
``build_agent``. The only differences are the system prompt and which extra
tools they mount. Filesystem tools (read_file, ls, ...) come from the
LocalShellBackend for everyone; manus is special-cased to strip them (pure
router).

This is the foundation for future user-customizable / pluggable agents: a new
agent is just a new entry here (and later, a row in an agents DB table).
"""

from __future__ import annotations

from typing import Any

# ─── system prompts ─────────────────────────────────────────────────────────

MANUS_PROMPT = """You are Manus, the entry routing agent. You have NO file
tools. Your only job is to decide, in ONE short sentence, who to delegate the
user's request to, then hand it off:

1. PURE CHAT / knowledge questions (greetings, "what is X"): answer directly
   from your own knowledge.

2. A SINGLE clear task ("implement X", "read Y", "investigate Z"): call
   `dispatch` with target_agent="coder" (changes) or "researcher" (read-only).

3. ANYTHING multi-step / needing coordination ("use a team", "research then
   build"): call `dispatch` with target_agent="teamleader".

CRITICAL: When you delegate, reply with ONE line (e.g. "Delegating to a
coder."). Do NOT restate the task, do NOT outline steps.
"""


TEAMLEADER_PROMPT = """You are a Team Leader coordinating specialist agents to
complete a task handed to you.

Your agents (via the `dispatch` tool):
- "researcher": read-only investigation (list/read/grep files).
- "coder": can read/write/edit/run files.

How to work:
1. Break the task into subtasks.
2. Delegate each with `dispatch` — give a CLEAR, DETAILED task. Choose mode:
   - mode="sync" when your NEXT step needs the result (serial orchestration).
   - mode="async" for independent parallel sub-tasks.
3. Read your `read_mailbox` for results; use `whiteboard_read` for full content.
4. When done, write a concise final summary.

Prefer delegating over doing the work yourself.
"""


RESEARCHER_PROMPT = (
    "You are a researcher agent. Investigate the codebase to answer the task. "
    "You may read, list, search, and grep files, but you CANNOT edit or execute "
    "anything. Return a concise findings summary."
)


CODER_PROMPT = (
    "You are a coder agent. Implement the requested change in the codebase. "
    "You may read, edit, write, and run files. Return a brief summary of what "
    "you changed."
)

# Backwards-compatible role_prompt() used by engine.start()
_ROLE_PROMPTS = {
    "researcher": RESEARCHER_PROMPT,
    "coder": CODER_PROMPT,
}


def role_prompt(role: str) -> str:
    """The system prompt for a role, or a sensible default."""
    return _ROLE_PROMPTS.get(role, f"You are a {role} agent. Complete the task.")


# ─── agent configuration registry ───────────────────────────────────────────
#
# Each entry: display_name, prompt, tools (extra tool factory names to mount),
# and flags. Filesystem tools come from the backend for all agents; manus has
# them stripped via ToolGuard so it's a pure router.

AGENT_CONFIGS: dict[str, dict[str, Any]] = {
    "manus": {
        "display_name": "Manus",
        "prompt": MANUS_PROMPT,
        "tools": ["dispatch"],          # only the delegation tool
        "is_entry": True,
        "strip_file_tools": True,       # pure router — no file access
    },
    "teamleader": {
        "display_name": "Team Leader",
        "prompt": TEAMLEADER_PROMPT,
        "tools": ["dispatch", "send_message", "read_mailbox",
                  "whiteboard_write", "whiteboard_read"],
        "strip_file_tools": False,
    },
    "coder": {
        "display_name": "Coder",
        "prompt": CODER_PROMPT,
        "tools": [],
        "allowed_tools": {"read_file", "write_file", "edit_file",
                          "list_directory", "ls", "glob", "grep", "execute"},
        "strip_file_tools": False,
    },
    "researcher": {
        "display_name": "Researcher",
        "prompt": RESEARCHER_PROMPT,
        "tools": [],
        "allowed_tools": {"read_file", "list_directory", "ls", "glob", "grep"},
        "strip_file_tools": False,
    },
}


# Backwards compatibility: ROLES (used by dispatch tool for validation +
# metadata). Conceptually these are just "agents you can dispatch to".
ROLES = {k: v for k, v in AGENT_CONFIGS.items() if k != "manus"}
