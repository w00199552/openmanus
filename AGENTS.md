# AGENTS.md

Workspace instructions for ZCode agents working in **OpenManus** (`D:\openmanus`).
Read this before editing. For deep context, also read `PROJECT_STATUS.md` first
(it is the project's long-term memory), then `ARCHITECTURE.md` / `ROADMAP.md` as needed.

## What this repo is

Multi-agent coding platform. Three runtime processes that talk over a **custom SSE
protocol** (NOT AG-UI / CopilotKit — those were removed):

- `backend/`  — Python 3.12+, FastAPI + deepagents + LangGraph. Port **8999**.
- `frontend/` — JS/JSX, vite + React 19 + **mobx** + tailwind + shadcn/ui. Port **5173**.
- `electron/` — desktop shell (frameless window), loads `localhost:5173` in dev.

Default model `GLM-5.2` over Anthropic protocol; `MODEL_PROVIDER=openai` switches to OpenAI-compatible.

## Commands

```bash
# All-at-once on Windows (kills ALL python.exe/node.exe/electron.exe first):
restart.bat

# Backend (terminal 1)
# Use `python -m uvicorn`, NOT `uv run uvicorn` — the latter hits a uv 0.11.24
# trampoline bug on Windows ("uv trampoline failed to canonicalize script path").
cd backend && uv run python -m uvicorn openmanus.main:app --reload --port 8999

# Frontend (terminal 2)
cd frontend && yarn install && yarn dev

# Electron desktop (terminal 3)
cd electron && npm run dev

# Lint / build frontend
cd frontend && yarn oxlint          # linter (see .oxlintrc.json)
cd frontend && yarn build           # vite build

# Backend tests (pytest, configured in backend/pyproject.toml under
# [tool.pytest.ini_options]; dev deps declared in [dependency-groups].dev)
cd backend && uv run pytest tests/                       # whole suite (~1s)
cd backend && uv run pytest tests/test_tool_guard.py -v  # one file
```

Backend tests run via **pytest** (declared as dev deps: `pytest`, `pytest-asyncio`).
Config lives in `backend/pyproject.toml`: `asyncio_mode = "auto"` (async test
functions need no per-test marker), `testpaths = ["tests"]`. No frontend test
suite / typecheck step exists yet.

## Critical layout gotchas (do not get these wrong)

- **`backend/agents/`, `backend/01_code/`, `backend/Z`, `backend/bfs*.py`, `backend/dfs*.py`,
  `tree_algorithms/`** — these are **gitignored runtime artifacts the agent writes into its
  workdir** (e.g. when running "implement BFS"). They are **NOT project source** — do not edit
  them as if they were. See `.gitignore`.
- **Built-in agents live in `backend/seed/agents/{Manus,Coder,Researcher,TeamLeader}/`**
  (`agent.yaml` + `prompt.md`). On first run they are copied to `~/.openmanus/agents/` and the
  copies are **never overwritten**. To change a built-in for all users, edit `backend/seed/`, not
  `~/.openmanus/`.
- User tools → `~/.openmanus/tools/`; skills → `~/.openmanus/skills/` (SKILL.md packs).
  Seeds for these are under `backend/seed/skills/`.
- Runtime DBs (`backend/data/checkpoints.db`, `sessions.db`) are gitignored.

## Architecture boundaries

- **Backend entry:** `backend/src/openmanus/main.py` (FastAPI app + lifespan). `api/` = HTTP
  routers (`sessions`, `streams`, `agents`, `files`, `skills`, `tools`). `engine.py` =
  `StreamEngine` (the execution heart). `agent_factory.py` = `build_agent`/`close_agent`.
  `channels.py` = in-process `asyncio.Queue` per session. `event_schema.py` = SSE frame schema.
- **Agent lifecycle = "Plan A: not resident".** Each `_stream` call does
  `build_agent(session_id)` → `astream` → `close_agent`. Do not cache agent instances; history
  survives because the checkpointer keys on `thread_id = session_id`.
- **Four built-in agents, strict roles:** Manus (entry router, dispatch-only),
  Coder (file read/write/execute), Researcher (read-only), TeamLeader (multi-step coord).
  `ToolGuardMiddleware` strips file tools from Manus. Keep Manus a pure router — do not push
  loop/orchestration into it (that is deferred to L3, see ROADMAP).
- **File ops are sandboxed via `LocalShellBackend(virtual_mode=True)`** — restricted to workdir,
  but `execute()` shell commands are NOT restricted (deepagents design). Be aware when touching
  `agent_factory._build_backend`.
- **Frontend data flow is strictly `view → store → service`** (mobx, unidirectional). Chat is
  **self-rendered**: `services/agent-service.js` posts, `runtime/streamClient.js` subscribes to
  SSE, `runtime/eventReducer.js` folds events into a render list. Do not reintroduce
  CopilotKit / AG-UI SDK.
- **SSE proxy:** vite proxies `/sessions`, `/scopes`, `/agents`, `/skills`, `/tools-api`,
  `/files`, `/workdir`, `/health` → `127.0.0.1:8999`. Frontend dev talks to backend directly
  via `VITE_BACKEND_URL` (see `frontend/.env.development`) because vite's proxy buffers event
  streams.

## Conventions

- **Indent:** 4 spaces everywhere (`.editorconfig`: js/jsx/ts/tsx/json/css/html/py = 4-space;
  Makefile = tab). **EOF:** LF. Final newline required; trim trailing whitespace **except in
  `.md`** (markdown keeps trailing whitespace — significant for hard line breaks).
- **Frontend:** double quotes, semicolons, `trailingComma: "es5"` (`.prettierrc`). Path alias
  `@/*` → `./src/*` (shadcn/ui convention; configured in both `vite.config.js` and
  `jsconfig.json`). oxlint rules: `react/rules-of-hooks` = error,
  `react/only-export-components` = warn.
- **Backend:** Python `>=3.12`, package name `openmanus`, built with `uv` (`uv_build`). No ORM —
  raw SQL + `aiosqlite` for the sessions/mailboxes/whiteboard tables. LangGraph checkpointer
  stores message content separately.
- **Logging:** backend uses `logging.basicConfig` at INFO; logger name `openmanus`.
- **Tests:** pytest under `backend/tests/`. `asyncio_mode = "auto"` — async `test_*` functions
  are run automatically, **do not add `@pytest.mark.asyncio` markers**. Tests that touch the
  filesystem (e.g. tool_loader, agent_loader) MUST use the `tmp_openmanus_home` fixture from
  `conftest.py` to isolate `~/.openmanus` — never write to the real user config. Test files
  live in `tests/test_*.py`; shared fixtures in `tests/conftest.py`.

## Windows-specific gotchas

- `main.py` **must** set `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` **before** any subprocess
  spawns — Chinese Windows defaults to cp936/GBK and crashes on UTF-8 command output. Do not
  move/remove that block or reorder imports above it.
- `restart.bat` does `taskkill /F /IM python.exe`, `node.exe`, `electron.exe` — it will kill
  unrelated processes too. Warn the user before suggesting it.
- The repo lives at `D:\openmanus` but docs historically reference `D:\OpenManus` /
  `D:\deepagents-opencode`. Treat those as the same place.

## Docs to read before touching sensitive areas

- `PROJECT_STATUS.md` — read first every session (dynamic project memory).
- `ARCHITECTURE.md` — module map, data flow, endpoint list, design decisions.
- `ROADMAP.md` — L1/L2/L3 plan; respect the "Manus stays pure router" decision.
- `docs/coder-gap.md` — Coder-vs-opencode design + which deepagents middlewares already exist
  (prefer configuring framework built-ins over hand-rolling).
