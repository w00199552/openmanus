"""Build the two agents: default (entry) + teamleader (team coordinator).

- **default**: the entry agent the user talks to. It can do simple things
  directly, OR delegate a large task to a background team via dispatch_to_team
  (non-blocking).
- **teamleader**: runs inside a team session, coordinates sub-agents via the
  synchronous dispatch_task (researcher/coder). Each delegation creates an
  isolated child session + message_links.

Both share the same model + filesystem backend + checkpointer.
"""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_core.language_models import BaseChatModel
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from .config import settings
from .middleware.tool_guard import ToolGuardMiddleware
from .store import get_checkpointer
from .tools import (
    make_dispatch_single_tool,
    make_dispatch_task_tool,
    make_dispatch_to_team_tool,
)

# Tools the DEFAULT entry agent must NOT see: it is a pure router + read-only
# chat. Writing/editing/executing is the sub-agents' job. `task` is deepagents'
# built-in subagent-dispatch tool — it would let the agent spawn its own
# sub-tasks and BYPASS our dispatch_single/dispatch_to_team routing, so it's
# stripped too. All stripped at BOTH the model-request layer (so the model
# doesn't see them) AND the tool-execution layer (so even a hallucinated call
# is rejected) via ToolGuardMiddleware.
DEFAULT_EXCLUDED_TOOLS = frozenset(
    {"write_file", "edit_file", "execute", "write_todos", "task"}
)

# The teamleader also must not use deepagents' built-in `task` tool — its only
# delegation path is our `dispatch_task` (which we track as sessions). File
# tools stay (the teamleader may inspect files), but `task` is blocked.
TEAMLEADER_EXCLUDED_TOOLS = frozenset({"task"})

DEFAULT_PROMPT = f"""{settings.system_prompt}

You are the DEFAULT entry agent — a ROUTER. You never do specialist work and you
never plan or break down tasks. Decide, in ONE short sentence, which lane a
request belongs to, then hand it off:

1. CASUAL CHAT / simple questions (greetings, explaining a concept, "what files
   are here"): answer yourself, using only read-only tools (ls, read_file, grep,
   glob). NEVER write/edit/execute.

2. A SINGLE clear specialist task ("implement X", "fix this file", "investigate
   Y"): call `dispatch_single` with target_agent="coder" or "researcher".

3. ANYTHING ELSE (multi-step, needs coordination, "use a team", "research then
   build", ambiguous scope): call `dispatch_to_team` and pass the user's request
   VERBATIM as task_description. Do NOT decompose it, do NOT assign roles, do NOT
   describe phases — deciding how to split the work and whom to involve is the
   team leader's job, not yours.

CRITICAL: When you choose lane 2 or 3, your reply must be ONE line stating you
handed it off (e.g. "Delegating to a coder." / "Starting a team."). Do NOT
restate the task, do NOT outline steps, do NOT mention what each member will do.
"""


TEAMLEADER_PROMPT = """You are a TEAM LEADER coordinating a team of specialist
sub-agents to complete a task handed to you.

Your sub-agents (via the `dispatch_task` tool):
- "researcher": read-only investigation (list/read/grep files). Use to explore
  the codebase, answer "what's there" questions.
- "coder": can read/write/edit/run files. Use to implement changes.

How to work:
1. Break the task into subtasks.
2. Delegate each subtask with dispatch_task, giving a CLEAR, DETAILED
   description (the sub-agent starts with no context — include file paths,
   goals, constraints).
3. Review results; delegate follow-ups if needed.
4. When done, write a concise final summary for the user.

Keep delegating until the task is complete. Prefer delegating over doing the
work yourself.
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
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        streaming=True,
        http_client=sync_http,
        http_async_client=async_http,
    )


def _build_backend(workdir: str) -> LocalShellBackend:
    return LocalShellBackend(
        root_dir=workdir,
        virtual_mode=False,
        inherit_env=True,
    )


async def _build_default_agent(
    workdir: str, checkpointer: Any, model: BaseChatModel
) -> CompiledStateGraph:
    """Build the default + teamleader agents bound to a specific workdir.

    The teamleader is created first and held by an indirect ref so the default
    agent's dispatch_to_team tool can launch it in the background.
    """
    backend = _build_backend(workdir)

    # teamleader (coordinates sub-agents via dispatch_task)
    team_agent_ref: dict = {}
    dispatch_task_tool = make_dispatch_task_tool(
        agent_ref=team_agent_ref, parent_workdir=workdir
    )
    teamleader = create_deep_agent(
        model=model,
        system_prompt=TEAMLEADER_PROMPT,
        tools=[dispatch_task_tool],
        backend=backend,
        checkpointer=checkpointer,
        middleware=[ToolGuardMiddleware(excluded=TEAMLEADER_EXCLUDED_TOOLS)],
        name="openmanus-teamleader",
    )
    team_agent_ref["agent"] = teamleader

    # default (entry router). It delegates to a SINGLE specialist via
    # dispatch_single (running the sub-agent on a graph with FULL tools) or to
    # a TEAM via dispatch_to_team. The sub-agent runs on the TEAMLEADER's graph
    # (unrestricted filesystem + dispatch_task), NOT the default's own graph —
    # because the default's write/execute tools are stripped by the exclusion
    # middleware, so a coder couldn't do its job on the default graph.
    default_agent_ref: dict = {}
    dispatch_single_tool = make_dispatch_single_tool(agent_ref=team_agent_ref)
    dispatch_to_team_tool = make_dispatch_to_team_tool(team_agent_ref=teamleader)
    default_agent = create_deep_agent(
        model=model,
        system_prompt=DEFAULT_PROMPT,
        tools=[dispatch_single_tool, dispatch_to_team_tool],
        backend=backend,
        checkpointer=checkpointer,
        # Strip write/execute tools so the router physically cannot do the
        # specialist work itself — it must delegate. (Guarded at both the
        # model-request and tool-execution layers.)
        middleware=[ToolGuardMiddleware(excluded=DEFAULT_EXCLUDED_TOOLS)],
        name="openmanus-default",
    )
    default_agent_ref["agent"] = default_agent
    return default_agent


# Per-workdir agent cache: workdir -> (default_agent, teamleader_agent).
# Agents are cheap to build but we avoid rebuilding on every request; a session
# reuses the cached agent for its workdir.
_agent_cache: dict[str, tuple] = {}
_default_checkpointer: Any = None
_default_model: BaseChatModel | None = None


async def get_agent_for_workdir(workdir: str) -> CompiledStateGraph:
    """Return the default agent bound to ``workdir`` (cached, built on demand).

    This enables per-session workdirs: each distinct workdir gets its own agent
    instance (with its own filesystem backend rooted there).
    """
    global _default_checkpointer, _default_model
    if _default_checkpointer is None:
        _default_checkpointer = await get_checkpointer()
    if _default_model is None:
        _default_model = _build_model()

    if workdir not in _agent_cache:
        _agent_cache[workdir] = await _build_default_agent(
            workdir, _default_checkpointer, _default_model
        )
    return _agent_cache[workdir]  # the default agent


async def build_agents() -> tuple[CompiledStateGraph, CompiledStateGraph]:
    """Build both agents at startup (for the configured default workdir).

    Returns (default_agent, teamleader_agent). The default agent holds an
    indirect ref to the teamleader (via dispatch_to_team -> team_runner).
    """
    checkpointer = await get_checkpointer()
    model = _build_model()

    # teamleader: coordinates sub-agents via dispatch_task ---------------
    team_agent_ref: dict = {}
    dispatch_task_tool = make_dispatch_task_tool(
        agent_ref=team_agent_ref, parent_workdir=settings.workdir
    )
    teamleader = create_deep_agent(
        model=model,
        system_prompt=TEAMLEADER_PROMPT,
        tools=[dispatch_task_tool],
        backend=_build_backend(settings.workdir),
        checkpointer=checkpointer,
        middleware=[ToolGuardMiddleware(excluded=TEAMLEADER_EXCLUDED_TOOLS)],
        name="openmanus-teamleader",
    )
    team_agent_ref["agent"] = teamleader

    # default: entry router — delegates to a single specialist (dispatch_single,
    # run on the TEAMLEADER's unrestricted graph) or a team (dispatch_to_team).
    # The default's own write/execute tools are stripped, so sub-agents must run
    # on a graph that still has them (the teamleader).
    default_agent_ref: dict = {}
    dispatch_single_tool = make_dispatch_single_tool(agent_ref=team_agent_ref)
    dispatch_to_team_tool = make_dispatch_to_team_tool(team_agent_ref=teamleader)
    default_agent = create_deep_agent(
        model=model,
        system_prompt=DEFAULT_PROMPT,
        tools=[dispatch_single_tool, dispatch_to_team_tool],
        backend=_build_backend(settings.workdir),
        checkpointer=checkpointer,
        # Strip write/execute tools so the router physically cannot do the
        # specialist work itself — it must delegate. (Guarded at both the
        # model-request and tool-execution layers.)
        middleware=[ToolGuardMiddleware(excluded=DEFAULT_EXCLUDED_TOOLS)],
        name="openmanus-default",
    )
    default_agent_ref["agent"] = default_agent

    # warm the cache for the default workdir (store the default agent)
    _agent_cache[settings.workdir] = default_agent
    _default_checkpointer = checkpointer
    _default_model = model

    return default_agent, teamleader
