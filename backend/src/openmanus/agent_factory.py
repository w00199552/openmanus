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

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from typing import Any

from .agent_loader import agent_loader
from .chat_model import ChatGLM
from .config import settings
from .middleware.agent_trace import AgentTraceMiddleware
from .middleware.tool_guard import ToolGuardMiddleware
from .store import get_checkpointer
from .tool_loader import tool_loader
from .tools.mailbox_tools import (
    make_dispatch_tool,
    make_read_mailbox_tool,
    make_send_message_tool,
)
from .tools.whiteboard_tools import (
    make_whiteboard_read_tool,
    make_whiteboard_write_tool,
)

# File tools that the pure-router (manus) must NOT have. Stripped via ToolGuard.
_FILE_TOOLS = frozenset(
    {"read_file", "write_file", "edit_file", "execute", "write_todos",
     "list_directory", "ls", "glob", "grep", "task"}
)

# Per-workdir cache for the ENTRY agent only (cheap reuse — it's stateless
# across turns thanks to the checkpointer). Dispatched agents are built fresh
# every time and NOT cached.
_entry_agent_cache: dict[str, CompiledStateGraph] = {}
_default_checkpointer: Any = None
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


def _resolve_session_id(config: Any) -> str:
    try:
        return ((config or {}).get("configurable") or {}).get("thread_id") or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _resolve_scope_id(config: Any) -> str | None:
    sid = _resolve_session_id(config)
    return sid if sid != "unknown" else None


def _build_tools(tool_names: list[str], workdir: str, agent_name: str = "") -> list:
    """Instantiate the extra tools listed in an agent's config.

    Resolution order per name:
      1. Built-in factory (dispatch / send_message / read_mailbox / whiteboard_*)
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
                session_id_fn=_resolve_session_id, scope_id_fn=_resolve_scope_id,
            ))
        elif tname == "whiteboard_read":
            tools.append(make_whiteboard_read_tool(scope_id_fn=_resolve_scope_id))
        else:
            # 2. user-defined tool (from ~/.openmanus/tools/)
            user_tool = tool_loader.get(tname)
            if user_tool is not None:
                tools.append(user_tool)
            else:
                logger.warning("unknown tool '%s' for agent '%s', skipping", tname, agent_name)
    return tools


# The entry agent name (hardcoded — the user-facing entry point).
ENTRY_AGENT = "Manus"


async def build_agent(name: str, workdir: str) -> CompiledStateGraph:
    """Create a FRESH, independent agent by name.

    Each call returns a new CompiledStateGraph with its OWN checkpointer
    instance — never reused, never shared. Sharing a checkpointer across
    concurrent astreams was the cross-talk root cause: langgraph's
    AsyncSqliteSaver is not safe for concurrent use on the same object, so a
    dispatched agent's chunks bled into the dispatcher's stream. A fresh
    checkpointer per agent (all pointing at the same DB file, isolated by
    thread_id) eliminates that.
    """
    global _default_model
    if _default_model is None:
        _default_model = _build_model()

    # Each agent gets its OWN checkpointer instance (own aiosqlite connection).
    # They all read/write the same DB file, isolated by thread_id. This is the
    # concurrency fix: no shared checkpointer object → no cross-talk.
    own_checkpointer = await get_checkpointer()

    cfg = agent_loader.get(name)
    if not cfg:
        raise ValueError(f"Unknown agent name: {name!r}. Available: {agent_loader.all_names()}")
    tools = _build_tools(cfg.get("tools", []), workdir, agent_name=name)
    excluded = _FILE_TOOLS if cfg.get("strip_file_tools") else frozenset({"task"})

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
        system_prompt=cfg["prompt"],
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


async def build_entry_agent(workdir: str = None) -> CompiledStateGraph:
    """Build (and cache) the entry agent for a workdir.

    The entry agent (manus) is the one the user talks to directly. Cached
    per-workdir since it's stateless across turns (its own checkpointer holds
    history). Dispatched agents are NOT cached — built fresh each time with
    their own checkpointer.
    """
    wd = workdir or settings.workdir
    if wd not in _entry_agent_cache:
        global _default_model
        if _default_model is None:
            _default_model = _build_model()
        _entry_agent_cache[wd] = await build_agent(ENTRY_AGENT, wd)
    return _entry_agent_cache[wd]

# Entry agent name is hardcoded — use ENTRY_AGENT constant.
