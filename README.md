# deepmanus

An [opencode](https://opencode.ai)-style AI coding agent clone, built with
**[deepagents](https://github.com/langchain-ai/deepagents)** (LangChain) on the
backend and a **direct AG-UI SSE** stream on the frontend (no CopilotKit).

## Architecture

Two services, talking over the AG-UI protocol (Server-Sent Events):

```
① Frontend (vite + react, JS/JSX)              ② Python backend
   react + mobx + tailwind + shadcn/ui          FastAPI + deepagents
   view → store → service (mobx)                AG-UI endpoint
   self-parsed AG-UI SSE stream                 create_deep_agent
        │                                            │
        │  POST /agents/main  (AG-UI SSE)            │
        └───────────────────────────────────────────►┘
            (vite dev proxy → :8999)
```

- **② Backend (`backend/`)** — `deepagents` agent with an OpenAI/Anthropic-
  compatible model, operating on the **real local filesystem**
  (`LocalShellBackend`) and persisting conversation history in a SQLite
  checkpointer. Exposed as a standard **AG-UI** endpoint at `POST /agents/main`.
- **① Frontend (`frontend/`)** — vite + react (JS/JSX) with **mobx**
  (`view → store → service` one-way data flow), **tailwindcss**, and
  **shadcn/ui**. The chat is **self-rendered**: `agentService.js` POSTs to the
  AG-UI endpoint and parses the SSE stream; `ChatStore` folds the events into a
  render list. No CopilotKit, no Express middleware.

> The original CopilotKit + Express middleware layer was removed because its
> message state was bound to internal Providers inaccessible without
> `<CopilotChat>`, blocking self-rendered chat. The frontend now streams
> AG-UI events straight from the Python backend.

## Prerequisites

- Python 3.12+ with [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ with `yarn` (or `npm`)

## Quick start

### 1. Configure the backend

```bash
cd backend
cp .env.example .env
# edit .env: set OPENAI_API_KEY / OPENAI_BASE_URL / MODEL
# any OpenAI-compatible endpoint works (OpenAI, OpenRouter, Ollama, LiteLLM, …)
```

### 2. Start both services

On Windows, double-click the launcher (kills any old services, then starts
backend + frontend fresh):

```
restart.bat
```

…or run them manually in two terminals:

```bash
# terminal 1 — Python backend (port 8999)
cd backend
uv run uvicorn openmanus.main:app --reload --port 8999

# terminal 2 — frontend (port 5173)
cd frontend
yarn install
yarn dev
```

Open http://localhost:5173 and chat. The agent reads/writes/runs files in
`backend/` (or `WORKDIR` from `.env`) and remembers the conversation across
restarts (SQLite at `backend/data/checkpoints.db`).

## Configuration

### Backend (`backend/.env`)

| Var | Default | Purpose |
|-----|---------|---------|
| `OPENAI_API_KEY` | — | API key for the model provider |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Any OpenAI-compatible base URL |
| `MODEL` | `gpt-4o-mini` | Model name |
| `WORKDIR` | server cwd | Directory the agent edits (real files) |
| `DATABASE_URL` | `sqlite:///./data/checkpoints.db` | History storage (or a postgres URL) |

## How the AG-UI bridge works

`backend/src/openmanus/agui_bridge.py` drives `agent.astream(...)` (LangGraph v2
streaming, `stream_mode=["messages","updates"]`, `subgraphs=True`) and re-emits
each chunk as a standard AG-UI event:

| deepagents / LangGraph | AG-UI event |
|---|---|
| run start | `RUN_STARTED` |
| `AIMessageChunk` text token | `TEXT_MESSAGE_*` |
| tool call (streamed) | `TOOL_CALL_START` / `TOOL_CALL_ARGS` |
| `ToolMessage` (result) | `TOOL_CALL_RESULT` / `TOOL_CALL_END` |
| node step | `STEP_STARTED` / `STEP_FINISHED` |
| exception | `RUN_ERROR` |
| run end | `RUN_FINISHED` |

The frontend parses these frames itself (`agentService.js`) and `ChatStore`
folds them into a render list (text deltas appended live, tool calls nested
under the assistant message that issued them).

## Frontend data flow

Strict one-way flow (views never call backends directly):

```
view (observer) ──action──► store (mobx) ──call──► service ──fetch──► backend
     ▲                            │
     └──── observable state ◄─────┘
```

The live chat (streaming tokens + tool calls) is fully self-rendered:
`agentService.streamAgent()` POSTs to `/agents/main` and dispatches each AG-UI
event to `ChatStore`, which mobx-react observes.

## Project layout

```
OpenManus/
├── backend/      # Python: FastAPI + deepagents + AG-UI endpoint
└── frontend/     # JS/JSX: vite + react + mobx + tailwind + shadcn (direct AG-UI SSE)
```
