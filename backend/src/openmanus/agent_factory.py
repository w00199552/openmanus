"""Agent factory — build fresh, independent agent instances by role.

Every agent (manus / TeamLeader / Coder / Researcher) is created the SAME way:
``build_agent(role, workdir)`` returns a brand-new CompiledStateGraph with its
own state. No agent instance is ever reused across runs — this is the cross-talk
fix (previously sub-agents reused the TeamLeader's single graph, and concurrent
astreams on the same object contaminated each other).

The checkpointer is SHARED (one DB) but each run uses its own thread_id
(= its session id), so histories stay isolated at the storage layer.
"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from .agent_loader import agent_loader
from .chat_model import ChatGLM
from .config import settings
from .db import session_store
from .middleware.agent_trace import AgentTraceMiddleware
from .middleware.tool_guard import ToolGuardMiddleware
from .store import get_checkpointer
from .tool_loader import tool_loader
from .tools.dispatch_tool import make_dispatch_tool
from .tools.mailbox_tools import make_read_mailbox_tool, make_send_message_tool
from .tools.whiteboard_tools import (
    make_whiteboard_read_tool,
    make_whiteboard_write_tool,
)

# Tools that deepagents injects by default (filesystem + execute + todos +
# the general-purpose subagent `task`). These are NOT instantiated by us —
# the framework registers them. We only decide which to KEEP via the agent's
# `tools` whitelist; any builtin not whitelisted is excluded at both the
# model-request layer (framework `_ToolExclusionMiddleware`) and the
# tool-execution layer (our `ToolGuardMiddleware`, which also blocks
# hallucinated calls).
#
# Source: deepagents 0.6.11 graph.py docstring + middleware/filesystem.py +
# langchain TodoListMiddleware + middleware/subagents.py (`task`).
# NOTE: `task` is injected by default (graph.py auto-adds a general-purpose
# subagent). Excluding it here keeps the built-in agents minimal; when an
# agent needs a synchronous sub-agent (ROADMAP P1-3), add `task` to its
# `tools` whitelist.
_BUILTIN_TOOLS = frozenset(
    {"write_todos", "ls", "read_file", "write_file", "edit_file",
     "glob", "grep", "execute", "task"}
)

logger = logging.getLogger(__name__)

_default_model: BaseChatModel | None = None


def _build_model() -> BaseChatModel:
    provider = settings.model_provider.lower()
    import httpx

    sync_http = httpx.Client(verify=settings.ssl_verify)
    async_http = httpx.AsyncClient(verify=settings.ssl_verify)

    if provider == "anthropic":
        return ChatAnthropic(
            model=settings.model,
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
            streaming=True,
            max_tokens=8192,
        )
    return ChatGLM(
        model=settings.model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        streaming=True,
        http_client=sync_http,
        http_async_client=async_http,
        extra_body={"thinking": {"type": "enabled"}},
        default_headers={"x-reasoning-format": "reasoning"}
    )


def _build_backend(workdir: str) -> LocalShellBackend:
    """Build the shell+filesystem backend for an agent's workdir.

    virtual_mode=True confines file operations (read/write/ls/glob/grep) to
    root_dir — agents see only their workdir, not the host filesystem.
    Shell commands (execute) still run on the host with cwd=root_dir, but
    that's constrained by the agent's prompt, not the backend.

    NOTE: virtual_mode does NOT sandbox shell execution. For true isolation,
    use a sandboxed backend (Docker/VM). This is sufficient for a local dev
    tool where you trust the agent.
    """
    return LocalShellBackend(root_dir=workdir, virtual_mode=True, inherit_env=True)


def compute_thread_id(topic_id: str, agent_name: str) -> str:
    """Compute the LangGraph checkpointer thread_id from topic + agent.

    thread_id = ``f"{topic_id}:{agent_name}"``. This is the memory-chain key:
    the same agent in the same topic shares a thread across multiple sessions
    (multiple executions), giving it memory continuity. Different topics or
    different agents get different threads (full isolation).

    Not stored in the DB — computed on the fly in build_agent / engine.
    """
    return f"{topic_id}:{agent_name}"


def _resolve_session_id(config: Any) -> str:
    """Extract the current session_id from a RunnableConfig.

    Phase 1 change: reads ``config["configurable"]["session_id"]`` instead of
    the old ``thread_id`` (which used to equal session_id). Now that session_id
    and thread_id are separate, tools must read session_id explicitly.
    """
    try:
        return ((config or {}).get("configurable") or {}).get("session_id") or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _resolve_topic_id(config: Any) -> str | None:
    """Extract the current topic_id from a RunnableConfig.

    Phase 1 change: renamed from _resolve_scope_id; reads
    ``config["configurable"]["topic_id"]``.
    """
    try:
        tid = ((config or {}).get("configurable") or {}).get("topic_id")
        return tid if tid else None
    except Exception:  # noqa: BLE001
        return None


def _resolve_tool_whitelist(declared: list[str] | set[str]) -> tuple[frozenset[str], frozenset[str], list[str]]:
    """Split an agent's declared `tools` into builtin/extras partitions.

    The `tools` field is a UNIFIED whitelist: it may contain deepagents
    builtins (``read_file``, ``execute``, ...), OpenManus builtins
    (``dispatch``, ``whiteboard_*``), and user-defined tools. This function
    partitions them so ``build_agent`` knows:

      * which builtins to KEEP (framework injects them, do not instantiate)
      * which builtins to EXCLUDE (hide from model + block via ToolGuard)
      * which NON-builtin names to pass to ``_build_tools`` for instantiation

    Args:
        declared: the agent's ``tools`` list/set from agent.yaml.

    Returns:
        ``(builtin_kept, builtin_excluded, extra_tool_names)`` where:
          - ``builtin_kept``    = builtins the agent DOES want (subset of
                                  ``_BUILTIN_TOOLS``)
          - ``builtin_excluded``= builtins to strip (``_BUILTIN_TOOLS -
                                  builtin_kept``)
          - ``extra_tool_names``= non-builtin names, sorted, for
                                  ``_build_tools``
    """
    declared_set = set(declared)
    builtin_kept = declared_set & _BUILTIN_TOOLS
    builtin_excluded = _BUILTIN_TOOLS - builtin_kept
    extra_tool_names = sorted(declared_set - _BUILTIN_TOOLS)
    return frozenset(builtin_kept), frozenset(builtin_excluded), extra_tool_names


def _build_tools(tool_names: list[str], workdir: str, agent_name: str = "") -> list:
    """Instantiate the NON-builtin tools listed in an agent's `tools` whitelist.

    deepagents built-in tools (``_BUILTIN_TOOLS``) are injected by the
    framework and must NOT be passed here — they're handled by the whitelist
    keep/exclude logic in ``build_agent``. This function only resolves names
    that are NOT builtins:

    Resolution order per name:
      1. OpenManus built-in factory (dispatch / send_message / read_mailbox /
         whiteboard_*)
      2. User-defined tool from tool_loader (~/.openmanus/tools/)
    """
    tools: list = []
    for tname in tool_names:
        # 1. built-in factories (with runtime params)
        if tname == "dispatch":
            tools.append(make_dispatch_tool(workdir=workdir))
        elif tname == "send_message":
            tools.append(make_send_message_tool())
        elif tname == "read_mailbox":
            tools.append(make_read_mailbox_tool())
        elif tname == "whiteboard_write":
            tools.append(make_whiteboard_write_tool(
                session_id_fn=_resolve_session_id, scope_id_fn=_resolve_topic_id,
            ))
        elif tname == "whiteboard_read":
            tools.append(make_whiteboard_read_tool(scope_id_fn=_resolve_topic_id))
        else:
            # 2. user-defined tool (from ~/.openmanus/tools/)
            user_tool = tool_loader.get(tname)
            if user_tool is not None:
                tools.append(user_tool)
            else:
                logger.warning("unknown tool '%s' for agent '%s', skipping", tname, agent_name)
    return tools


def _resolve_prompt(raw_prompt: str, self_name: str) -> str:
    """Replace placeholders in an agent's prompt with dynamic content.

    Supported placeholders:
      {{AGENTS}} — list of all OTHER agents (name + description), so the
                   entry agent knows who it can dispatch to. Excludes itself.
    """
    if "{{AGENTS}}" not in raw_prompt:
        return raw_prompt

    lines = []
    for agent_name in sorted(agent_loader.all_names()):
        if agent_name == self_name:
            continue  # don't list yourself
        agent_cfg = agent_loader.get(agent_name) or {}
        desc = (agent_cfg.get("description") or "").strip()
        if desc:
            lines.append(f"- {agent_name}: {desc}")
        else:
            lines.append(f"- {agent_name}")

    return raw_prompt.replace("{{AGENTS}}", "\n".join(lines))


async def build_agent(session_id: str) -> CompiledStateGraph:
    """Create a FRESH, independent agent for a session.

    Reads the session's name + workdir + topic_id from the DB, then builds a
    new CompiledStateGraph with its OWN checkpointer.

    thread_id (checkpointer key) is computed as ``f"{topic_id}:{name}"`` via
    :func:`compute_thread_id`. The engine constructs the LangGraph config with
    this thread_id (phase 2). This function reads topic_id from the session
    row so the caller (engine) can compute thread_id without an extra DB query.

    Agent instances are NOT cached — every call creates a new one. The
    checkpointer persists conversation history in the DB, so rebuilding
    an agent does NOT lose context. Callers should close the agent after
    use (see ``close_agent``).
    """
    global _default_model
    if _default_model is None:
        _default_model = _build_model()

    s = await session_store.get(session_id)
    if not s:
        raise ValueError(f"session not found: {session_id}")
    # name may be None for legacy sessions (created before name was stored).
    # Fall back to kind-based defaults: root → Manus, team → TeamLeader.
    name = s.get("name")
    if not name:
        name = "TeamLeader" if s.get("kind") == "team" else "Manus"
    workdir = s.get("workdir") or settings.workdir

    # Each agent gets its OWN checkpointer instance (own aiosqlite connection).
    own_checkpointer = await get_checkpointer()

    cfg = agent_loader.get(name)
    if not cfg:
        raise ValueError(f"Unknown agent name: {name!r}. Available: {agent_loader.all_names()}")

    # Unified tool whitelist. An agent's `tools` list declares EVERYTHING it
    # can use — deepagents builtins, OpenManus builtins, and user tools alike.
    #   - builtins listed here  → kept (framework injects them)
    #   - builtins NOT here     → excluded (framework hides them AND
    #                             ToolGuardMiddleware blocks hallucinated calls)
    #   - non-builtins here     → instantiated by _build_tools below
    _kept, excluded, extra_tool_names = _resolve_tool_whitelist(cfg.get("tools", []))
    tools = _build_tools(extra_tool_names, workdir, agent_name=name)

    # Build backend: CompositeBackend routes /skills/ to read-only, everything
    # else to the working directory (read-write).
    from deepagents.backends.composite import CompositeBackend
    from .readonly_backend import ReadOnlyFilesystemBackend
    from .skill_loader import skill_loader, SKILLS_DIR

    default_backend = _build_backend(workdir)
    routes = {}
    # Mount /skills/ as read-only if the agent has skills configured.
    skill_names = cfg.get("skills", [])
    if skill_names and SKILLS_DIR.exists():
        routes["/skills/"] = ReadOnlyFilesystemBackend(root_dir=str(SKILLS_DIR))
    backend = CompositeBackend(default=default_backend, routes=routes) if routes else default_backend

    # Build skill paths for SkillsMiddleware (absolute paths to skill dirs).
    skill_paths = []
    for sname in skill_names:
        sdir = skill_loader.skill_dir(sname)
        if sdir:
            skill_paths.append(str(sdir))

    return create_deep_agent(
        model=_default_model,
        system_prompt=_resolve_prompt(cfg["prompt"], name),
        tools=tools,
        backend=backend,
        checkpointer=own_checkpointer,
        skills=skill_paths if skill_paths else None,
        middleware=[
            ToolGuardMiddleware(excluded=excluded),
            AgentTraceMiddleware(name=name),
        ],
        name=name,
    )


async def close_agent(agent: CompiledStateGraph) -> None:
    """Close an agent's checkpointer connection to release resources.

    Safe to call multiple times — checks for the connection before closing.
    """
    cp = getattr(agent, "checkpointer", None)
    if cp is not None:
        conn = getattr(cp, "conn", None)
        if conn is not None:
            try:
                await conn.close()
            except Exception:  # noqa: BLE001
                pass
