# OpenManus

> **可进化的多 Agent 编码平台。**
> 后端 Python(FastAPI + deepagents),前端 vite + react + mobx,桌面 Electron。
> 当前处于 **L1 基础编码平台** 阶段 —— 详见 [ROADMAP.md](./ROADMAP.md)。

OpenManus 不是又一个单机 CLI coding agent。它是一个三层叠加的系统:

- **L1 基础编码平台**(当前)—— 对标 opencode,保留 server 化 / 可配置多 agent / skills / mailbox 的差异化优势。
- **L2 知识管理 + skill 自学习进化**(规划中)—— 对标 Hermes,llmwiki + book2skill/ctx2skill。
- **L3 Loop Engine 循环工程**(规划中)—— 对标 multica + 业界 loop engineering,基于 agent + 中间件构建可复用 loop 模板。

## 它和 opencode 的区别

OpenManus 在 L1 阶段保留了以下 opencode 没有的**结构性优势**:

- **Server 化 / 可嵌入** —— FastAPI + 自定义 SSE 事件协议,天然支持多客户端、远程、嵌入式场景。
- **可配置多 Agent** —— agent 是文件(`agent.yaml` + `prompt.md`),热更新,`{{AGENTS}}` 占位符动态注入路由表。
- **Agent 间协作基础设施** —— Mailbox(dispatch/result/chat)+ Whiteboard(共享 artifact)+ scope fan-in 群聊视图。
- **Skills 一等公民** —— `SKILL.md` 文件包 + CompositeBackend 只读挂载 `/skills/`。
- **Sandbox 文件浏览器** —— 懒加载目录树 + watchdog SSE 实时刷新 + 右键 CRUD,接近 IDE 体验。

## 架构

两个服务,通过 SSE(Server-Sent Events)通信:

```
① Frontend (vite + react, JS/JSX)             ② Backend (Python)
   react + mobx + tailwind + shadcn/ui          FastAPI + deepagents (LangGraph)
   view → store → service (mobx 单向数据流)     自定义 SSE 事件协议
   自解析 SSE 流                                  create_deep_agent
        │                                            │
        │  POST /sessions/:id/messages (触发 agent)  │
        │  GET  /stream?scope=... (订阅 SSE)         │
        └───────────────────────────────────────────►┘
              (vite dev proxy → :8999)
```

- **② Backend (`backend/`)** —— `deepagents` agent,双 provider(Anthropic 协议 / OpenAI 兼容),操作**真实本地文件系统**(`LocalShellBackend`,`virtual_mode=True` 限制文件操作在 workdir 内),对话历史存 SQLite checkpointer。对外暴露自定义 SSE 事件协议。
- **① Frontend (`frontend/`)** —— vite + react(JS/JSX)+ **mobx**(`view → store → service` 单向数据流)+ **tailwindcss** + **shadcn/ui**。聊天是**自渲染**的:`agentService.js` 发消息、`streamClient.js` 订阅 SSE,`eventReducer.js` 把事件折叠成渲染列表。不依赖 CopilotKit / AG-UI SDK。
- **③ Electron (`electron/`)** —— frameless 桌面窗口,dev 模式加载 `localhost:5173`。

> 历史说明:早期版本基于 CopilotKit + Express 中间件,因其消息状态绑定到内部 Provider、无法脱离 `<CopilotChat>` 自渲染而已移除。前端现在直接消费后端 SSE 流。

## 前置条件

- Python 3.12+ with [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ with `yarn`(或 `npm`)

## 快速开始

### 1. 配置后端

```bash
cd backend
cp .env.example .env
# 编辑 .env,按下方"模型配置"两选一
```

### 2. 启动所有服务

Windows 下双击启动器(会先杀旧进程,再依次起 backend + frontend + electron):

```
restart.bat
```

…或手动在两个终端起:

```bash
# 终端 1 —— Python 后端(端口 8999)
cd backend
uv run uvicorn openmanus.main:app --reload --port 8999

# 终端 2 —— 前端(端口 5173)
cd frontend
yarn install
yarn dev
```

打开 http://localhost:5173 开始对话。Agent 在 `WORKDIR`(默认后端 cwd)下读写运行文件,对话历史持久化到 `backend/data/checkpoints.db`,重启不丢。

## 模型配置(`backend/.env`)

支持两档 provider,通过 `MODEL_PROVIDER` 切换:

| Mode | `MODEL_PROVIDER` | 适用 | 关键变量 |
|---|---|---|---|
| **A. Anthropic 协议**(默认) | `anthropic` | BigModel GLM / Anthropic / Z.ai | `MODEL=GLM-5.2` + `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic` |
| **B. OpenAI 兼容** | `openai` | OpenAI / OpenRouter / Ollama / LiteLLM / 公司内网 | `OPENAI_API_KEY` + `OPENAI_BASE_URL` + `MODEL` |

其他常用变量:

| 变量 | 默认 | 用途 |
|---|---|---|
| `SSL_VERIFY` | `true` | 设 `false` 跳过 TLS 校验(公司内网自签证书) |
| `WORKDIR` | 后端 cwd | agent 操作的根目录(真实文件) |
| `DATABASE_URL` | `sqlite:///./data/checkpoints.db` | 历史存储(可切 `postgresql+psycopg://...`) |
| `HOST` / `PORT` | `127.0.0.1` / `8999` | 后端监听 |

## SSE 事件协议

前后端之间走**自定义 SSE 事件协议**(非 AG-UI)。每个事件都带 `session_id` + `message_id` + `speaker`,这样一条 fan-in 群聊流可以自归因 —— 前端按 `session_id` 把帧分发回各参与者的视图。

| 事件 | 字段 | 说明 |
|---|---|---|
| `message_start` | `session_id`, `message_id`, `speaker` | 一条消息开始 |
| `text_delta` | `session_id`, `message_id`, `speaker`, `delta` | 文本流式 token |
| `thinking_delta` | `session_id`, `message_id`, `speaker`, `delta` | 推理过程流式(GLM `reasoning_content`) |
| `message_end` | `session_id`, `message_id`, `speaker` | 一条消息结束 |
| `tool_call_start` | `session_id`, `message_id`, `speaker`, `call_id`, `tool` | 工具调用开始 |
| `tool_call_args` | `session_id`, `call_id`, `args_json` | 工具参数流式 |
| `tool_call_result` | `session_id`, `call_id`, `result` | 工具结果 |
| `tool_call_end` | `session_id`, `call_id` | 工具调用结束 |
| `step_start` / `step_end` | `session_id`, `node` | 节点步骤 |
| `mailbox` | … | agent 间消息(dispatch/result/chat) |
| `error` | `session_id`, `message` | 错误 |
| `done` | `session_id` | 该 session 本轮结束 |

流以 `data: [DONE]\n\n` 收尾(所有参与 session 都 `done` 之后)。完整定义见 `backend/src/openmanus/event_schema.py`。

## 核心 Agent

四个内置 agent,都是**文件式可配置**的(首次运行从 `backend/seed/agents/` 复制到 `~/.openmanus/agents/`,之后用户自定义不被覆盖):

| Agent | 职责 | 工具集 |
|---|---|---|
| **Manus** | 入口路由,识别任务类型派给专家 | 仅 `dispatch`(无文件工具) |
| **Coder** | 编码执行:读/写/改/跑文件 | deepagents 文件工具 + `execute` |
| **Researcher** | 只读调研:列/读/搜/grep | deepagents 只读工具 |
| **TeamLeader** | 多步任务协调:拆任务 + dispatch | `dispatch` + mailbox + whiteboard |

agent 间通过 **Mailbox** 异步通信(dispatch 派活、result 回传、chat 闲聊),通过 **Whiteboard** 共享 artifact。`{{AGENTS}}` 占位符在 prompt 里动态注入"可派生的其他 agent"列表。

## `~/.openmanus/` 目录

首次启动后由 `seed_builtin()` 生成:

```
~/.openmanus/
  agents/          — 每个 agent 一个目录(agent.yaml + prompt.md)
  tools/           — 用户自定义工具(tool.yaml + entry.py)
  skills/          — SKILL.md 文件包(scripts/ + references/ + assets/)
```

## 项目结构

```
OpenManus/
├── ROADMAP.md         # 三层方案与演进路线(长期蓝图)
├── ARCHITECTURE.md    # 架构详解(模块/数据流/端点/设计决策)
├── PROJECT_STATUS.md  # 项目进展记忆(动态更新)
├── restart.bat        # Windows 启动脚本
├── backend/           # Python:FastAPI + deepagents + 自定义 SSE 协议
│   ├── src/openmanus/
│   ├── seed/          # 内置 agent / tool / skill 种子(首次复制到 ~/.openmanus/)
│   └── pyproject.toml # 包名 openmanus,uv 构建
├── frontend/          # JS/JSX:vite + react + mobx + tailwind + shadcn
└── electron/          # 桌面客户端(frameless window)
```

## 进一步阅读

- [ROADMAP.md](./ROADMAP.md) —— 三层方案(L1 基础编码 / L2 知识进化 / L3 Loop Engine)与演进路线
- [ARCHITECTURE.md](./ARCHITECTURE.md) —— 后端架构、模块职责、数据流、端点清单、设计决策
- [PROJECT_STATUS.md](./PROJECT_STATUS.md) —— 项目动态记忆(每个会话开始优先读它恢复上下文)

## 端口

- 后端 **8999**,前端 5173,Electron dev 加载 `localhost:5173`。
