"""Eval infrastructure: isolated DB + workdir for running Coder on fixtures.

This module sets up the sandbox the eval driver (run_eval.py) needs:

  * A throwaway SQLite DB (DATABASE_URL pointed at a temp path) so eval never
    touches the real sessions.db / checkpoints.db. Must be set BEFORE importing
    openmanus modules, because db.py / store.py resolve the path at import time.
  * A temp workdir per task: a COPY of the fixture's starter/ tree (or an empty
    dir for from-scratch tasks). Coder writes into this copy, so the fixture
    itself stays pristine and each eval run starts from a known state.
  * A git init in the workdir (for tasks that have a starter), so run_eval can
    measure "did Coder touch unrelated lines" via `git diff`.
  * Helpers to build a Coder agent for a session and collect its tool-call
    sequence while streaming.

NOT a pytest conftest — eval runs as a standalone script (`run_eval.py`), not
under pytest. Named conftest_eval.py (not conftest.py) on purpose so pytest
does not auto-import it during normal test collection.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ─── 1. Isolate the DB BEFORE any openmanus import ──────────────────────────
# Resolve a temp path and export it as DATABASE_URL. db.py and store.py both
# derive their SQLite path from settings.database_url, which reads this env var
# at import time. Setting it here means the eval's sessions/checkpoint tables
# land in the temp dir, not alongside the real backend/data/*.db.

_EVAL_ROOT = Path(__file__).resolve().parent
_FIXTURES_ROOT = _EVAL_ROOT / "fixtures"
_REPORTS_ROOT = _EVAL_ROOT / "reports"
_BACKEND_ROOT = _EVAL_ROOT.parent.parent

# Create the temp DB dir once per process; reuse for all tasks in this run.
_DB_TEMPDIR = tempfile.mkdtemp(prefix="openmanus_eval_db_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(_DB_TEMPDIR) / 'checkpoints.db'}")

# Now safe to import openmanus (settings will pick up our DATABASE_URL).
from openmanus.agent_factory import build_agent, close_agent  # noqa: E402
from openmanus.db import init_db, session_store  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

logger = logging.getLogger("openmanus.eval")


# ─── 2. Per-task workdir (copy of fixture starter) ──────────────────────────


def prepare_workdir(task_name: str) -> Path:
    """Copy fixture[task_name]/starter/ → a fresh temp dir; git-init it.

    For tasks without a starter/ (e.g. bfs, which is from-scratch), the workdir
    is just an empty temp dir. Returns the workdir Path.
    """
    fixture = _FIXTURES_ROOT / task_name
    if not fixture.exists():
        raise FileNotFoundError(f"no fixture named {task_name!r} at {fixture}")

    workdir = Path(tempfile.mkdtemp(prefix=f"openmanus_eval_{task_name}_"))

    starter = fixture / "starter"
    if starter.exists():
        shutil.copytree(starter, workdir, dirs_exist_ok=True)

    # git-init so run_eval can diff "what Coder changed". If git isn't
    # available or fails, we silently skip diff-based scoring — it's a
    # secondary signal, not the primary one.
    try:
        subprocess.run(
            ["git", "init", "-q"], cwd=str(workdir),
            check=True, capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "add", "-A"], cwd=str(workdir),
            check=True, capture_output=True, timeout=5,
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "fixture baseline"],
            cwd=str(workdir),
            # git needs an identity for commit; set one just for this call.
            env={**os.environ,
                 "GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@local",
                 "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@local"},
            check=True, capture_output=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        logger.warning("git not available in %s — diff-based scoring will be skipped", workdir)

    return workdir


# ─── 3. Build Coder + collect tool calls while streaming ────────────────────


@dataclass
class ToolCallRecord:
    """One tool invocation observed during the agent stream."""
    name: str
    args: str  # raw JSON-ish args string, as streamed
    result_preview: str = ""


@dataclass
class AgentRunResult:
    """Everything run_coder() collects from one agent invocation."""
    final_text: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    error: str | None = None
    message_count: int = 0


async def _ensure_db() -> None:
    """Initialize everything build_agent needs that main.py's lifespan would do.

    eval skips main.py, so we must reproduce the minimum bootstrap:
      * agent_loader.load_all() — build_agent reads agent config from here.
        Without it, agent_loader._configs is empty and build_agent raises
        "Unknown agent name: 'Coder'".
      * tool_loader / skill_loader — in case the deployed Coder references
        user tools or skills in its tools whitelist.
      * init_db() — CREATE TABLE IF NOT EXISTS on the temp DB.

    We deliberately do NOT call agent_loader.seed_builtin() — eval tests the
    AS-DEPLOYED ~/.openmanus/agents/, and seeding could mutate it.
    """
    from openmanus.agent_loader import agent_loader
    if not agent_loader.configs:
        agent_loader.load_all()
        logger.info("eval: loaded %d agents from %s", len(agent_loader.configs), agent_loader.dir)
    from openmanus.tool_loader import tool_loader
    tool_loader.load_all()
    from openmanus.skill_loader import skill_loader
    skill_loader.load_all()
    await init_db()


async def run_coder(task_prompt: str, workdir: str, *, max_turns: int = 40) -> AgentRunResult:
    """Build a Coder agent, stream it on task_prompt, collect observability.

    The agent runs in `workdir` (a temp copy of the fixture). We stream the
    LangGraph chunks directly — NOT through engine.py / SSE — so eval captures
    tool calls without needing the full session/channel machinery.

    `max_turns` caps the agent's recursion limit so a runaway loop can't burn
    unbounded tokens. One "turn" (model call + tool execution) costs ~2-6
    recursion steps in LangGraph depending on middleware, so the limit is set
    generously above max_turns.
    """
    await _ensure_db()

    # Create a session row with name=Coder and the temp workdir. build_agent
    # reads name+workdir from this row.
    session = await session_store.create(
        kind="subagent", name="Coder",
        title=f"eval: {Path(workdir).name}",
        workdir=workdir,
    )
    session_id = session["id"]

    result = AgentRunResult()
    agent = await build_agent(session_id)
    config = {
        "configurable": {"thread_id": session_id},
        # LangGraph counts each node visit (model, tools, middleware hooks) as
        # one recursion step. A normal coding turn = model + tools ≈ 2-6 steps.
        # 40 turns × ~6 = 240, with headroom for middleware.
        "recursion_limit": max_turns * 6,
    }

    # pending tool calls: name+args streamed, waiting for their ToolMessage
    pending: dict[str, ToolCallRecord] = {}

    try:
        async for chunk in agent.astream(
            {"messages": [HumanMessage(content=task_prompt)]},
            config=config,
            stream_mode=["messages", "updates"],
            subgraphs=False,
            version="v2",
        ):
            _absorb_chunk(chunk, result, pending)
        result.final_text = await _extract_final_text(agent, config)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent stream failed for session %s", session_id)
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        await close_agent(agent)

    return result


def _absorb_chunk(chunk, result: AgentRunResult, pending: dict) -> None:
    """Extract tool-call / text signals from a LangGraph v2 stream chunk.

    LangGraph v2 with stream_mode=list yields DICT chunks, not tuples:
        {"type": "messages"|"updates", "ns": (...), "data": ...}
      * type=="messages": data is (message, metadata). message may be an
        AIMessageChunk (carrying tool_call_chunks) or a ToolMessage (result).
      * type=="updates": data is {node_name: state_delta}. state_delta often
        has a "messages" list — we count those for a loose turn counter.
    """
    if not isinstance(chunk, dict):
        return
    kind = chunk.get("type")
    data = chunk.get("data")
    if kind == "messages":
        msg = data[0] if isinstance(data, tuple) and data else None
        if msg is None:
            return
        _handle_message(msg, result, pending)
    elif kind == "updates":
        if isinstance(data, dict):
            for node_state in data.values():
                msgs = (node_state or {}).get("messages") if isinstance(node_state, dict) else None
                if isinstance(msgs, list):
                    result.message_count += len(msgs)


def _handle_message(msg, result: AgentRunResult, pending: dict) -> None:
    # Streamed assistant tool-call chunks. LangChain streams these as a sequence
    # of partial dicts; the FIRST usually carries {"name":..., "id":...} and
    # subsequent ones carry {"args": "<json fragment>"} with name/id absent or
    # empty. So we key on id whenever present, and tolerate missing name.
    tcc = getattr(msg, "tool_call_chunks", None) or []
    for c in tcc:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or ""
        cid = c.get("id") or ""
        args = c.get("args")
        # Create the record lazily on the first chunk that carries an id.
        if cid and cid not in pending:
            rec = ToolCallRecord(name=name or "(streaming)", args="")
            pending[cid] = rec
            result.tool_calls.append(rec)
        if cid and cid in pending:
            rec = pending[cid]
            if name and (rec.name == "(streaming)" or not rec.name):
                rec.name = name
            if args:
                rec.args += str(args)
    # Tool result message — attach the preview to the pending record.
    if type(msg).__name__ == "ToolMessage":
        tcid = getattr(msg, "tool_call_id", None)
        content = getattr(msg, "content", "")
        if tcid and tcid in pending:
            preview = str(content)[:120].replace("\n", " ")
            pending[tcid].result_preview = preview


async def _extract_final_text(agent, config) -> str:
    """Read the last AI message's text content from the agent's final state."""
    try:
        state = await agent.aget_state(config)
        messages = (state.values or {}).get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", "")
            if getattr(msg, "type", "") == "ai" and content:
                if isinstance(content, list):
                    return " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ).strip()
                return str(content).strip()
    except Exception:  # noqa: BLE001
        logger.debug("could not extract final text", exc_info=True)
    return ""


# ─── 4. Load a fixture's task.md / check.py ─────────────────────────────────


def load_task(task_name: str) -> tuple[str, Any]:
    """Return (task_prompt, check_fn) for a fixture.

    task_prompt is the contents of fixture[task_name]/task.md.
    check_fn is the loaded `check(workdir: Path) -> dict` callable.
    """
    fixture = _FIXTURES_ROOT / task_name
    task_file = fixture / "task.md"
    if not task_file.exists():
        raise FileNotFoundError(f"fixture {task_name!r} has no task.md")
    prompt = task_file.read_text(encoding="utf-8")

    check_path = fixture / "check.py"
    if not check_path.exists():
        raise FileNotFoundError(f"fixture {task_name!r} has no check.py")
    spec = importlib.util.spec_from_file_location(f"eval_check_{task_name}", check_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "check"):
        raise AttributeError(f"{check_path} has no `check` function")
    return prompt, mod.check


def list_tasks() -> list[str]:
    """All fixture dirs that have both task.md and check.py."""
    out = []
    for d in sorted(_FIXTURES_ROOT.iterdir()):
        if d.is_dir() and (d / "task.md").exists() and (d / "check.py").exists():
            out.append(d.name)
    return out
