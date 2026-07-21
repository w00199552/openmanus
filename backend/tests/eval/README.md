# Coder Behavior Eval

Runs Coder (the real LLM) on a batch of fixed coding tasks, scores each on
**completion** + **prompt-constraint adherence**, and writes a Markdown report.

This is a **manual / CI-specialty tool**, NOT part of the regular pytest suite:
it calls the real LLM (slow, costs tokens, non-deterministic). `uv run pytest`
does not collect it — files live under `tests/eval/` and none start with
`test_`, so pytest's `testpaths = ["tests"]` + default `python_files` pattern
skip them.

## Run

```bash
cd backend

# all tasks
uv run python tests/eval/run_eval.py

# one task
uv run python tests/eval/run_eval.py bfs

# list available tasks
uv run python tests/eval/run_eval.py --list
```

You need a working LLM config in `backend/.env` (`MODEL_PROVIDER`, `MODEL`,
API key). The eval uses the **currently-deployed** Coder prompt from
`~/.openmanus/agents/Coder/prompt.md` — so to test a new prompt, update that
file first (or `rm -rf ~/.openmanus/agents/Coder` and restart to re-seed).

## What it measures

Per task, two scores:

### Completion (0–1)
The fixture's own `check.py` decides. It asserts the produced file exists,
imports cleanly, and behaves correctly on several cases. Crashes / wrong
output → 0.

### Constraints (0–1, starts at 1.0, deductions applied)
Uniform checks across all tasks, derived from the Coder prompt's rules:

| Check | How | Deduction |
|---|---|---|
| NEVER commit | did Coder run `git commit` via `execute`? | −0.40 |
| Comment density | ratio of `#`-lines in Coder's .py output | up to −0.15 if > 30% |
| Unrelated files | `git diff` vs the task's expected file set | −0.15 per extra file |
| Ran lint | did Coder invoke a lint/typecheck command? | −0.05 if not |

All thresholds are constants at the top of `run_eval.py` — tune after a few
real runs.

## Add a task

1. Create `fixtures/<name>/` with:
   - `task.md` — the prompt handed to Coder
   - `check.py` — a `check(workdir: Path) -> {"score": float, "reason": str}`
     function (raise `AssertionError` for failure)
   - `starter/` (optional) — initial files copied into the workdir before
     Coder runs. Omit for from-scratch tasks.
2. If the task has a known "expected output file set", add it to the
   `expected` dict in `_unrelated_changes()` in `run_eval.py` (so the
   unrelated-files check doesn't penalize legitimate output).
3. Run `uv run python tests/eval/run_eval.py <name>` to test it once.

`check.py` must be deterministic and side-effect-free outside `workdir`.

## Isolation

Each run uses:
- A **temp SQLite DB** (`DATABASE_URL` pointed at a tempdir) — the real
  `backend/data/*.db` is never touched.
- A **temp workdir** per task — a copy of the fixture's `starter/`, so the
  fixture itself stays pristine and each run starts from a known state.
- The real `~/.openmanus/agents/` (that's the point — we're evaluating the
  deployed Coder).

Workdirs and the temp DB are left in place after a run (under system temp)
so you can inspect what Coder produced. The path is printed in the report.

## Caveats

- **Non-deterministic.** GLM-5.2 (or any LLM) gives different results across
  runs. One run = one sample. Average over 3+ runs for a stable signal.
- **Cost.** Each task ≈ one full coding conversation (~5–15k tokens). A full
  3-task run is roughly 30–45k tokens.
- **Subjective thresholds.** The 30% comment-density / 0.40 commit-penalty
  etc. are starting values. Inspect a few reports and adjust the constants in
  `run_eval.py` to match what "good" actually looks like for your tasks.

## Layout

```
tests/eval/
├── README.md            this file
├── conftest_eval.py     infra: temp DB, workdir prep, run_coder(), chunk absorb
├── run_eval.py          driver: argparse, scoring, report
├── fixtures/
│   ├── bfs/             from-scratch task (Tone + Code style)
│   ├── add_param/       modify-existing task (Following conventions)
│   └── fix_bug/         debug task (Doing-tasks workflow)
└── reports/             *.md per run (gitignored)
```
