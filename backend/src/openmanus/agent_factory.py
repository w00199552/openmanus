"""Build the two agents: default (entry) + teamleader (team coordinator).

Unified model: both agents share one graph (the teamleader's, which keeps the
filesystem tools the sub-agents need). The default agent's own graph has those
tools stripped by ToolGuard, so sub-agents MUST run on the teamleader's graph.

The dispatch primitive is now ONE tool (`dispatch`) with a mode parameter:
  * default agent    → dispatch(..., mode="async")  [fire-and-forget]
  * teamleader       → dispatch(..., mode="sync"|"async") [chooses per step]
Plus `dispatch_to_team` (default → background teamleader), and mailbox +
whiteboard tools so agents can talk to each other and share artefacts.
"""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_core.language_models import BaseChatModel
from langchain_anthropic import ChatAnthropic
from langgraph.graph.state import CompiledStateGraph

from .chat_model import ChatGLM
from .config import settings
from .middleware.tool_guard import ToolGuardMiddleware
from .store import get_checkpointer
from .tools.mailbox_tools import (
    make_dispatch_tool,
    make_read_mailbox_tool,
    make_send_message_tool,
    make_start_team_tool,
)
from .tools.whiteboard_tools import (
    make_whiteboard_read_tool,
    make_whiteboard_write_tool,
)

# Tools the DEFAULT entry agent must NOT see: it is a pure router + read-only
# chat. Writing/editing/executing is the sub-agents' job. `task` is deepagents'
# built-in subagent-dispatch tool — it would let the agent spawn its own
# sub-tasks and BYPASS our dispatch routing, so it's stripped too. Guarded at
# BOTH the model-request and tool-execution layers via ToolGuardMiddleware.
DEFAULT_EXCLUDED_TOOLS = frozenset(
    {"write_file", "edit_file", "execute", "write_todos", "task"}
)

# The teamleader also must not use deepagents' built-in `task` tool — its only
# delegation path is our `dispatch` (which we track as sessions). File tools
# stay (the teamleader may inspect files), but `task` is blocked.
TEAMLEADER_EXCLUDED_TOOLS = frozenset({"task"})

DEFAULT_PROMPT = f"""{settings.system_prompt}

You are the DEFAULT entry agent — a ROUTER. You never do specialist work and you
never plan or break down tasks. Decide, in ONE short sentence, which lane a
request belongs to, then hand it off:

1. CASUAL CHAT / simple questions (greetings, explaining a concept, "what files
   are here"): answer yourself, using only read-only tools (ls, read_file, grep,
   glob). NEVER write/edit/execute.

2. A SINGLE clear specialist task ("implement X", "fix this file", "investigate
   Y"): call `dispatch` with target_agent="coder" or "researcher" (mode defaults
   to async — the task runs in the background and the user watches it).

3. ANYTHING ELSE (multi-step, needs coordination, "use a team", "research then
   build", ambiguous scope): call `dispatch_to_team` and pass the user's request
   VERBATIM as the task. Do NOT decompose it, do NOT assign roles, do NOT
   describe phases — deciding how to split the work and whom to involve is the
   team leader's job, not yours.

CRITICAL: When you choose lane 2 or 3, your reply must be ONE line stating you
handed it off (e.g. "Delegating to a coder." / "Starting a team."). Do NOT
restate the task, do NOT outline steps, do NOT mention what each member will do.
"""


TEAMLEADER_PROMPT = """You are a TEAM LEADER coordinating specialist sub-agents
to complete a task handed to you.

Your sub-agents (via the `dispatch` tool):
- "researcher": read-only investigation (list/read/grep files). Use to explore
  the codebase, answer "what's there" questions.
- "coder": can read/write/edit/run files. Use to implement changes.

How to work:
1. Break the task into subtasks.
2. Delegate each subtask with `dispatch`, giving a CLEAR, DETAILED task (the
   sub-agent starts with no context — include file paths, goals, constraints).
   Choose the mode deliberately:
   - mode="sync" when your NEXT step needs this sub-agent's result (serial
     orchestration: research, then build on the findings).
   - mode="async" when sub-tasks are independent and can run together (dispatch
     several, then collect results from your mailbox / the whiteboard).
3. Read your `read_mailbox` for results from async dispatches; use
   `whiteboard_read` to fetch a result's full content by its whiteboard ref.
4. When a sub-agent's result is large, encourage them to write it to the
   whiteboard (whiteboard_write) so it doesn't get lost passing through context.
5. When the whole task is done, write a concise final summary for the user.

Prefer delegating over doing the work yourself.
"""


def _build_model() -> BaseChatModel:
    provider = settings.model_provider.lower()
    # For self-signed 公司内网证书, set SSL_VERIFY=false in .env. We inject a
    # verify-disabled httpx client into ChatOpenAI (the OpenAI-compatible path
    # used by company/internal models). ChatAnthropic doesn't accept a custom
    # http client, so for it we rely on httpx's env (CURL_CA_BUNDLE / etc.) or
    # the default verify behaviour.
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
    # GLM via BigModel's native OpenAI-compatible endpoint. We use ChatGLM (a
    # ChatOpenAI subclass) because plain ChatOpenAI discards GLM's non-standard
    # `reasoning_content` field — ChatGLM._convert_chunk_to_generation_chunk
    # preserves it so the thinking trace streams through.
    # thinking.type=enabled (passed via extra_body) gates reasoning_content on.
    # x-reasoning-format: reasoning — required by some deployments (e.g. company
    # ascendvllm) to actually emit reasoning_content in the response.
    return ChatGLM(
        model=settings.model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        streaming=True,
        http_client=sync_http,
        http_async_client=async_http,
        extra_body={"thinking": {"type": "enabled"}},
        default_headers={"x-reasoning-format": "reasoning"},
    )


def _build_backend(workdir: str) -> LocalShellBackend:
    return LocalShellBackend(
        root_dir=workdir,
        virtual_mode=False,
        inherit_env=True,
    )


def _resolve_session_id(config: Any) -> str:
    """Pull the calling session id out of a runnable config (best-effort)."""
    try:
        return (
            ((config or {}).get("configurable") or {}).get("thread_id") or "unknown"
        )
    except Exception:  # noqa: BLE001
        return "unknown"


def _resolve_scope_id(config: Any) -> str | None:
    """Best-effort scope id from config (sync, may return None)."""
    # The teamleader's session id IS the scope id for its team.
    sid = _resolve_session_id(config)
    return sid if sid != "unknown" else None


async def _build_agents_for_workdir(
    workdir: str, checkpointer: Any, model: BaseChatModel
) -> tuple[CompiledStateGraph, CompiledStateGraph]:
    """Build the teamleader + default agents bound to a workdir.

    Returns (default_agent, teamleader_agent). Both are wired to dispatch onto
    the teamleader's graph (which retains the filesystem tools).
    """
    backend = _build_backend(workdir)

    # --- teamleader (coordinates sub-agents via dispatch) --------------------
    team_agent_ref: dict = {}
    teamleader_dispatch = make_dispatch_tool(
        agent_ref=team_agent_ref, workdir=workdir, default_mode="sync",
    )
    teamleader = create_deep_agent(
        model=model,
        system_prompt=TEAMLEADER_PROMPT,
        tools=[
            teamleader_dispatch,
            make_send_message_tool(),
            make_read_mailbox_tool(),
            make_whiteboard_write_tool(
                session_id_fn=_resolve_session_id, scope_id_fn=_resolve_scope_id,
            ),
            make_whiteboard_read_tool(scope_id_fn=_resolve_scope_id),
        ],
        backend=backend,
        checkpointer=checkpointer,
        middleware=[ToolGuardMiddleware(excluded=TEAMLEADER_EXCLUDED_TOOLS)],
        name="openmanus-teamleader",
    )
    team_agent_ref["agent"] = teamleader

    # --- default (entry router) --------------------------------------------
    # dispatch_single → dispatch on the teamleader's graph (async default).
    # dispatch_to_team → launch a background teamleader on a new team session.
    default_dispatch = make_dispatch_tool(
        agent_ref=team_agent_ref, workdir=workdir, default_mode="async",
    )
    dispatch_to_team = make_start_team_tool(
        team_agent_ref=teamleader, workdir=workdir,
    )
    default_agent = create_deep_agent(
        model=model,
        system_prompt=DEFAULT_PROMPT,
        tools=[default_dispatch, dispatch_to_team],
        backend=backend,
        checkpointer=checkpointer,
        # Strip write/execute tools so the router physically cannot do the
        # specialist work itself — it must delegate. (Guarded at both the
        # model-request and tool-execution layers.)
        middleware=[ToolGuardMiddleware(excluded=DEFAULT_EXCLUDED_TOOLS)],
        name="openmanus-default",
    )
    return default_agent, teamleader


# Per-workdir agent cache: workdir -> (default_agent, teamleader_agent).
_agent_cache: dict[str, tuple[CompiledStateGraph, CompiledStateGraph]] = {}
_default_checkpointer: Any = None
_default_model: BaseChatModel | None = None


async def get_agent_for_workdir(workdir: str) -> CompiledStateGraph:
    """Return the default agent bound to ``workdir`` (cached, built on demand)."""
    global _default_checkpointer, _default_model
    if _default_checkpointer is None:
        _default_checkpointer = await get_checkpointer()
    if _default_model is None:
        _default_model = _build_model()

    if workdir not in _agent_cache:
        _agent_cache[workdir] = await _build_agents_for_workdir(
            workdir, _default_checkpointer, _default_model
        )
    return _agent_cache[workdir][0]  # the default agent


async def get_teamleader_for_workdir(workdir: str) -> CompiledStateGraph:
    """Return the teamleader agent bound to ``workdir`` (cached)."""
    if workdir not in _agent_cache:
        await get_agent_for_workdir(workdir)
    return _agent_cache[workdir][1]


async def build_agents() -> tuple[CompiledStateGraph, CompiledStateGraph]:
    """Build both agents at startup (for the configured default workdir).

    Returns (default_agent, teamleader_agent). Also warms the per-workdir cache.
    """
    checkpointer = await get_checkpointer()
    model = _build_model()
    default_agent, teamleader = await _build_agents_for_workdir(
        settings.workdir, checkpointer, model
    )
    _agent_cache[settings.workdir] = (default_agent, teamleader)
    _default_checkpointer = checkpointer
    _default_model = model
    return default_agent, teamleader
