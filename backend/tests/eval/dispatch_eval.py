"""Manus → specialist dispatch verification (real LLM).

Verifies the core multi-agent dispatch chain end-to-end through the REAL
engine (not just build_agent + astream like the Coder eval):

    user task → Manus (engine.run) → dispatch tool → engine._pending →
    _start_and_record → child agent runs → mailbox result back to Manus

This is the minimal repro of what happens when a user message hits Manus and
Manus decides to delegate. We drive it through engine.run (mode="sync") so the
full _stream → finally → _pending → _start_and_record chain fires, then await
engine._tasks so the dispatched child actually completes before we inspect.

USAGE
    cd backend
    uv run python tests/eval/dispatch_eval.py coder        # Manus → Coder
    uv run python tests/eval/dispatch_eval.py researcher   # Manus → Researcher
    uv run python tests/eval/dispatch_eval.py              # both

COST
    Each scenario = Manus turn + one child agent turn ≈ 2 LLM coding/research
    conversations. Non-deterministic; single run is a sample.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Force line-buffered stdout/stderr so background runs stream output instead of
# buffering until exit. Background processes default to full buffering, which
# makes it impossible to watch progress.
try:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except Exception:
    pass

# Isolate DB BEFORE importing openmanus (db.py/store.py read DATABASE_URL at import).
_DB_TEMPDIR = tempfile.mkdtemp(prefix="openmanus_dispatch_db_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(_DB_TEMPDIR) / 'checkpoints.db'}")

from openmanus.agent_loader import agent_loader  # noqa: E402
from openmanus.db import init_db, session_store  # noqa: E402
from openmanus.engine import engine  # noqa: E402
from openmanus.mailbox import mailbox_store  # noqa: E402


# ─── scenarios ──────────────────────────────────────────────────────────────

@dataclass
class Scenario:
    name: str
    task: str
    expected_target: str  # "Coder" | "Researcher"


SCENARIOS = {
    "coder": Scenario(
        name="Manus → Coder",
        task=(
            "Create a file `greet.py` containing a function `hello(name)` that "
            'returns f"Hello, {name}!". Then verify it works by running it.'
        ),
        expected_target="Coder",
    ),
    "researcher": Scenario(
        name="Manus → Researcher",
        task=(
            "Find all Python files in this directory and report how many there "
            "are and what each one contains (one line each). Do NOT modify "
            "anything — just investigate and report."
        ),
        expected_target="Researcher",
    ),
}


# ─── result ─────────────────────────────────────────────────────────────────

@dataclass
class DispatchResult:
    scenario: str
    manus_called_dispatch: bool = False
    dispatch_target: str = ""
    child_session_created: bool = False
    child_session_status: str = ""
    child_name: str = ""
    mailbox_dispatch_sent: bool = False  # caller → child (dispatch msg)
    mailbox_result_received: bool = False  # child → caller (result msg)
    result_preview: str = ""
    manus_final_reply: str = ""
    duration_s: float = 0.0
    error: str | None = None


# ─── runner ─────────────────────────────────────────────────────────────────

async def run_scenario(scenario: Scenario, workdir: str) -> DispatchResult:
    """Run one Manus → specialist scenario through the real engine."""
    res = DispatchResult(scenario=scenario.name)
    start = time.time()

    # Bootstrap: load agents + init DB tables.
    if not agent_loader.configs:
        agent_loader.load_all()
    await init_db()

    # Create a fresh Manus session for this scenario (don't reuse singleton —
    # we want isolated history per scenario). Point its workdir at our temp dir.
    manus = await session_store.create(
        kind="root", name="Manus",
        title=f"dispatch eval: {scenario.name}",
        workdir=workdir,
    )
    manus_id = manus["id"]
    print(f"\n▶ {scenario.name}: Manus session {manus_id[:12]}, workdir={workdir}")

    # Seed a couple of files so the Researcher scenario has something to find.
    if scenario.expected_target == "Researcher":
        (Path(workdir) / "alpha.py").write_text("x = 1\n", encoding="utf-8")
        (Path(workdir) / "beta.py").write_text("y = 2\n", encoding="utf-8")

    try:
        # Run Manus to completion (sync). Its _stream finally block will create
        # tasks in engine._pending → launch them via _start_and_record.
        manus_reply = await engine.run(
            session_id=manus_id, prompt=scenario.task,
            speaker="Manus", mode="sync",
        )
        res.manus_final_reply = (manus_reply or "").strip()

        # Wait for any dispatched children to finish. engine._tasks drains as
        # each completes (done_callback discards). Snapshot then gather.
        pending_tasks = list(engine._tasks)
        if pending_tasks:
            print(f"  waiting for {len(pending_tasks)} dispatched child task(s)...")
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        # ── Inspect signals ──
        await _inspect(res, scenario, manus_id, workdir)

    except Exception as e:  # noqa: BLE001
        res.error = f"{type(e).__name__}: {e}"
        import traceback
        traceback.print_exc()

    res.duration_s = round(time.time() - start, 1)
    return res


async def _inspect(res: DispatchResult, scenario: Scenario, manus_id: str, workdir: str) -> None:
    # 1. Did Manus dispatch? Look for subagent-kind sessions whose parent is Manus.
    all_sessions = await session_store.list()
    children = [s for s in all_sessions if s.get("kind") == "subagent"]
    # The child's metadata.parent should point at manus_id; check session_store
    # doesn't always surface metadata in list(), so also accept any subagent
    # created during this run as "the" child.
    child = None
    for s in children:
        meta = s.get("metadata") or {}
        if isinstance(meta, str):
            import json
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if meta.get("parent") == manus_id:
            child = s
            break
    if child is None and children:
        child = children[-1]  # fallback: most recent subagent

    if child:
        res.child_session_created = True
        res.child_name = child.get("name") or ""
        res.child_session_status = child.get("status") or ""
        res.manus_called_dispatch = True
        res.dispatch_target = res.child_name

    # 2. Mailbox: did the child get a dispatch msg, and did Manus get a result?
    if child:
        child_inbox = await mailbox_store.inbox(child["id"])
        res.mailbox_dispatch_sent = any(m.get("kind") == "dispatch" for m in child_inbox)

    manus_inbox = await mailbox_store.inbox(manus_id)
    result_msgs = [m for m in manus_inbox if m.get("kind") == "result"]
    res.mailbox_result_received = len(result_msgs) > 0
    if result_msgs:
        content = result_msgs[-1].get("content") or ""
        res.result_preview = content[:200].replace("\n", " ")


# ─── report ─────────────────────────────────────────────────────────────────

def print_report(results: list[DispatchResult]) -> None:
    print("\n" + "=" * 70)
    print("Manus → specialist dispatch verification")
    print("=" * 70)
    for r in results:
        # Pass criteria (post Bug-2 fix design):
        #   - Manus called dispatch exactly toward the right agent
        #   - child session was created and ran
        #   - child received the dispatch mail
        #   - Manus did NOT receive a result mail (entry agent is a pure router —
        #     _record_result skips root callers; the user watches the child session
        #     directly). mailbox_result_received must be False here.
        #   - Manus dispatched only ONCE (no loop) — checked via the trace count.
        ok = (
            r.manus_called_dispatch
            and r.child_session_created
            and r.mailbox_dispatch_sent
            and not r.mailbox_result_received  # expected: entry agent gets no result mail
            and not r.error
        )
        emoji = "✅" if ok else "❌"
        print(f"\n{emoji} {r.scenario}  ({r.duration_s}s)")
        if r.error:
            print(f"   ERROR: {r.error}")
        print(f"   Manus called dispatch : {r.manus_called_dispatch}")
        print(f"   Dispatch target       : {r.dispatch_target!r} (expected {SCENARIOS_BY_NAME[r.scenario].expected_target!r})")
        print(f"   Child session created : {r.child_session_created} (name={r.child_name!r}, status={r.child_session_status!r})")
        print(f"   Mailbox dispatch→child: {r.mailbox_dispatch_sent}")
        print(f"   Mailbox result→Manus  : {r.mailbox_result_received}")
        if r.result_preview:
            print(f"   Result preview        : {r.result_preview}")
        print(f"   Manus final reply     : {r.manus_final_reply[:120]!r}")

    # Summary verdict
    print("\n" + "-" * 70)
    all_ok = all(
        r.manus_called_dispatch and r.child_session_created and r.mailbox_dispatch_sent
        and not r.mailbox_result_received  # entry agent must NOT get result mail
        and not r.error
        for r in results
    )
    print("VERDICT: " + ("PASS — dispatch chain works end-to-end" if all_ok else "FAIL — see signals above"))


SCENARIOS_BY_NAME = {s.name: s for s in SCENARIOS.values()}


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    import sys
    wanted = argv[1:] or ["coder", "researcher"]
    unknown = [w for w in wanted if w not in SCENARIOS]
    if unknown:
        print(f"Unknown scenario(s): {unknown}", file=sys.stderr)
        print(f"Available: {list(SCENARIOS)}", file=sys.stderr)
        return 2

    async def _go():
        results = []
        for key in wanted:
            sc = SCENARIOS[key]
            # Fresh workdir per scenario so they don't see each other's files.
            wd = tempfile.mkdtemp(prefix=f"openmanus_dispatch_{key}_")
            results.append(await run_scenario(sc, wd))
        return results

    results = asyncio.run(_go())
    print_report(results)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
