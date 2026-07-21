# OpenManus 架构文档(ARCHITECTURE)

> 本文档面向新成员,系统性地介绍 **OpenManus** 项目的整体架构、技术栈、模块职责、数据流与设计决策。
> 后端代码位于 [`backend/src/openmanus`](./backend/src/openmanus),是一个基于 **FastAPI + LangGraph + deepagents** 构建的智能体(Agent)服务,对外通过**自定义 SSE 事件协议**与前端交互。
> 本文与代码同步,如发现偏差以代码为准。当前所处阶段见 [ROADMAP.md](./ROADMAP.md)。

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 技术栈](#2-技术栈)
- [3. 目录结构](#3-目录结构)
- [4. 核心模块说明](#4-核心模块说明)
- [5. 系统架构与数据流](#5-系统架构与数据流)
- [6. 数据模型](#6-数据模型)
- [7. API 设计概览](#7-api-设计概览)
- [8. 关键设计决策与约定](#8-关键设计决策与约定)
- [9. 快速上手](#9-快速上手)

---

## 1. 项目概述

**OpenManus** 是一个 opencode 风格的 AI 编码 Agent 平台(`pyproject.toml`:`name = "openmanus"`,`version = "0.1.0"`),目标是构建一个**可进化的多 Agent 编码平台**(三层规划见 ROADMAP)。

### 定位

基于 LangChain 生态的 `deepagents` 库构建智能体,能对**真实本地文件系统**进行读 / 写 / 执行操作,对外暴露**自定义 SSE 事件协议**接口,供前端(vite + react + mobx,自渲染 SSE 流)消费。

### 一句话架构

> `FastAPI 应用 → POST /sessions/:id/messages 触发 agent → StreamEngine 把 LangGraph 流转成统一 SSE 事件 → 驱动 deepagents 智能体图(Manus 入口路由 + Coder/Researcher 专家 + TeamLeader 协调)→ 操作 LocalShellBackend(真实文件系统,workdir 内 virtual_mode 隔离)+ SQLite checkpointer 持久化历史`

### 通信方式

前端通过两个端点与后端通信(vite dev proxy 转发到后端 `:8999`):

- `POST /sessions/:id/messages` —— 发消息并**触发** agent run(后台非阻塞,立即返回)
- `GET /stream?scope=<team_id>` 或 `?sessions=id1,id2` —— **订阅** SSE 事件流

这种"POST 触发 + GET 订阅"的分离是流可靠性的关键:POST 是普通 JSON 请求(无流式响应生命周期问题),GET 是纯 SSE 订阅。

### 四 Agent 架构

| Agent | 层级 | 职责 | 工具集 |
|---|---|---|---|
| **Manus** | 入口路由 | 单例(`id="manus"`,不可删),识别任务类型派给专家;纯 chat 直接答 | 仅 `dispatch`(文件工具被 `ToolGuardMiddleware` 硬剥除) |
| **Coder** | 专家 | 编码执行:读/写/改/跑文件 | deepagents 文件工具 + `execute` |
| **Researcher** | 专家(只读) | 调研:列/读/搜/grep | deepagents 只读工具 |
| **TeamLeader** | 协调 | 多步任务拆解 + dispatch + 收结果 | `dispatch` + mailbox + whiteboard |

> **"新启会话"= reset**(对单例 Manus 执行 `adelete_thread`),不是新建 session。

### 核心价值

1. 把 LangGraph 的流式输出桥接为**自定义 speaker-aware SSE 事件**,每帧带 `session_id` + `speaker`,一条 fan-in 流可自归因到各参与者视图;
2. **四 Agent 架构** + 文件式配置(agent.yaml + prompt.md,热更新,`{{AGENTS}}` 动态注入路由表);
3. **Agent 间协作基础设施** —— Mailbox(dispatch/result/chat) + Whiteboard(共享 artifact) + scope fan-in 群聊;
4. **双层持久化**(checkpointer 存消息内容 + sessions.db 存会话元数据/协作空间);
5. 对真实本地文件系统操作(`LocalShellBackend`,`virtual_mode=True` 把文件操作限制在 workdir 内)。

---

## 2. 技术栈

来源:`backend/pyproject.toml`。

| 类别 | 依赖 | 版本要求 | 用途 |
|---|---|---|---|
| 语言 | Python | `>=3.12`(`requires-python`) | `.python-version` 固定版本 |
| 构建/包管理 | `uv`(`uv_build`) | `>=0.11.24,<0.12.0` | 锁文件 `uv.lock`;`[tool.uv] package=true`,`module-name = "openmanus"` |
| Web 框架 | `fastapi` | `>=0.115` | 异步 HTTP 服务 |
| ASGI 服务器 | `uvicorn[standard]` | `>=0.34` | 启动:`uv run uvicorn openmanus.main:app --reload --port 8999` |
| 配置 | `pydantic-settings` | `>=2.5` | `.env` 驱动 `BaseSettings` |
| 环境变量 | `python-dotenv` | `>=1.0` | `.env` 加载 |
| Agent 核心 | `deepagents` | `>=0.1` | `create_deep_agent` 编排智能体 |
| LLM 框架 | `langchain` | `>=0.3` | LangChain 基础 |
| LLM 提供商 | `langchain-openai` | `>=0.2` | OpenAI 兼容路径 |
| | `langchain-anthropic` | **未在 pyproject 声明 ⚠️** | `agent_factory.py` 直接 `from langchain_anthropic import ChatAnthropic`;当前由传递依赖引入 |
| Agent 编排 | `langgraph` | `>=0.6` | 状态图 + checkpointer |
| 持久化/checkpoint | `langgraph-checkpoint-sqlite` | `>=2.0` | 默认 SQLite saver |
| | `langgraph-checkpoint-postgres` | **运行时动态 import** | 切 Postgres 时用,非声明依赖 |
| 数据库驱动 | `aiosqlite` | `>=0.22.1` | 会话表原生 SQL |
| 文件监听 | `watchdog` | `>=6.0.0` | Sandbox 文件浏览器实时刷新 |

### 关键技术点

- **无独立 ORM**:会话表用**原生 SQL + aiosqlite**,无 SQLAlchemy / Tortoise 等。
- **无消息队列中间件**:agent 间实时分发用**进程内 `asyncio.Queue`**(`channels.ChannelRegistry`)。MVP 设计,进程重启会丢失运行中的任务。
- **默认数据库**:SQLite(`data/checkpoints.db` 消息内容 + `data/sessions.db` 会话元数据),可切换 Postgres。
- **默认模型**:`GLM-5.2`,走 Anthropic 协议(BigModel:`https://open.bigmodel.cn/api/anthropic`);通过 `MODEL_PROVIDER` 可切 OpenAI 兼容。
- **UTF-8 强制**:`main.py` 在 import 前设 `PYTHONUTF8=1` + `PYTHONIOEDING=utf-8`,避免中文 Windows 下子进程 cp936 解码崩溃。

---

## 3. 目录结构

```
D:/OpenManus/
├── ROADMAP.md                          # 三层方案与演进路线(长期蓝图)
├── ARCHITECTURE.md                     # 本文档(架构说明)
├── PROJECT_STATUS.md                   # 项目进展记忆(动态更新)
├── README.md                           # 项目总说明
├── restart.bat                         # Windows 启动脚本(杀旧进程 + 起 backend/frontend/electron)
├── backend/                            # Python 后端
│   ├── src/openmanus/
│   │   ├── main.py                     # FastAPI app + lifespan(加载 agents/tools/skills + init_db + ensure_manus)
│   │   ├── config.py                   # Settings(.env):provider/model/key/workdir/port=8999
│   │   ├── db.py                       # sessions 表 CRUD + ensure_manus + 迁移
│   │   ├── agent_factory.py            # build_agent(session_id) + close_agent + _resolve_prompt
│   │   ├── store.py                    # get_checkpointer:SQLite / Postgres
│   │   ├── engine.py                   # StreamEngine:_stream(内部 build+close)/ run / start
│   │   ├── channels.py                 # ChannelRegistry + drain_single + fan_in + drain_sessions
│   │   ├── event_schema.py             # 统一 SSE 事件 schema + frame 编码
│   │   ├── mailbox.py                  # MailboxStore:agent 间消息 + wakeup handler
│   │   ├── whiteboard.py              # WhiteboardStore:artifact CRUD
│   │   ├── agent_loader.py             # 从 ~/.openmanus/agents/ 加载(YAML + prompt.md)+ seed_builtin
│   │   ├── tool_loader.py              # 从 ~/.openmanus/tools/ 加载用户定义工具
│   │   ├── skill_loader.py             # 从 ~/.openmanus/skills/ 加载 SKILL.md
│   │   ├── readonly_backend.py         # ReadOnlyFilesystemBackend(virtual_mode=True)
│   │   ├── chat_model.py               # ChatGLM —— 保留 reasoning_content
│   │   ├── api/                        # HTTP 路由层(见 §7)
│   │   ├── middleware/                 # ToolGuard / AgentTrace / LLMTrace
│   │   └── tools/                      # mailbox_tools / whiteboard_tools / roles
│   ├── seed/                           # 内置 agent/tool/skill 种子(首次复制到 ~/.openmanus/)
│   │   └── agents/{Manus,Coder,Researcher,TeamLeader}/
│   ├── data/                           # 运行时 DB(checkpoints.db + sessions.db)
│   └── pyproject.toml                  # 包名 openmanus,uv 构建
├── frontend/                           # JS/JSX 前端
│   └── src/
│       ├── views/                      # Workspace/ChatPane/SessionList/Playground/AgentsView
│       ├── components/                 # chat/sandbox/ui 子目录
│       ├── stores/                     # RootStore(SessionStore/AgentRuntime/SandboxStore/AgentStore/SkillStore)
│       └── runtime/                    # eventReducer/messageStore/streamClient
└── electron/                           # 桌面客户端(frameless window,IPC 窗口控制)
```

### 各目录职责速览

| 目录 | 职责 |
|---|---|
| `backend/src/openmanus/` | 后端核心包(所有业务逻辑) |
| `backend/seed/` | 内置 agent/tool/skill 种子,首次运行复制到 `~/.openmanus/`(之后不覆盖) |
| `backend/data/` | 运行时 SQLite DB(gitignore) |
| `frontend/src/` | 前端源码(mobx 单向数据流) |
| `electron/` | Electron 桌面壳 |

---

## 4. 核心模块说明

### 4.1 应用入口 — `main.py`

- 构建 `FastAPI(title="openmanus")`,挂 CORS + 6 个 router。
- `lifespan`:启动时 `seed_builtin()` → `agent_loader.load_all()` → `tool_loader.load_all()` → `skill_loader.load_all()` → `init_db()` → `ensure_manus()`(单例入口 session)→ 从最近 session 恢复 workdir。
- Windows UTF-8 修复:import 前设 `PYTHONUTF8=1`。

### 4.2 配置 — `config.py`

`Settings(BaseSettings)`,从 `.env` 加载。关键字段:

- **Provider/模型**:`model_provider`(`anthropic` / `openai`)+ `model`(默认 `GLM-5.2`)。
- **Anthropic 凭据**:`anthropic_api_key` + `anthropic_base_url`(默认 BigModel)。
- **OpenAI 凭据**:`openai_api_key` + `openai_base_url`。
- **TLS**:`ssl_verify`(公司内网自签证书设 `false`)。
- **文件系统**:`workdir`(默认 cwd)。
- **持久化**:`database_url`(默认 `sqlite:///./data/checkpoints.db`)。
- **服务**:`host=127.0.0.1`,`port=8999`,`cors_origins=*`。

### 4.3 持久化(双层分离)

#### 4.3.1 LangGraph checkpointer(消息内容层)— `store.py`

`get_checkpointer()` 按 `DATABASE_URL` 选 SQLite / Postgres saver。**消息内容(对话历史)**存这里,按 `thread_id = session_id` 隔离。

#### 4.3.2 会话存储(元数据 + 协作空间)— `db.py`

**会话元数据 + agent 间消息 + 共享 artifact** 存这里(独立文件 `sessions.db`,与 checkpointer 的 `checkpoints.db` 同级)。

三张表:`sessions`(参与者注册表)+ `mailboxes`(agent 间消息)+ `whiteboard`(共享 artifact)。详见 §6。

### 4.4 Agent 构建 — `agent_factory.py`

**核心原则:agent 实例不缓存、不常驻(方案 A)。** 每次 `_stream` 时按 `session_id` 临时 build,跑完 `close_agent` 丢弃。历史不丢,因为 checkpointer 连同一个 SQLite DB,按 `thread_id` 隔离。

- `build_agent(session_id)` —— 从 DB 查 `name` + `workdir` → 新 checkpointer → `_resolve_prompt`(替换 `{{AGENTS}}` 占位符)→ `_build_tools` → `create_deep_agent`。
- `_build_backend(workdir)` —— `LocalShellBackend(root_dir=workdir, virtual_mode=True, inherit_env=True)`。**virtual_mode 把文件操作限制在 workdir 内**(`ls`/`read`/`write`/`glob`/`grep` + `..` 路径遍历被拒),但 `execute()` shell 命令不受限(deepagents 设计)。
- `_build_tools(tool_names, workdir)` —— 按 agent 配置实例化额外工具:`dispatch` / `send_message` / `read_mailbox` / `whiteboard_write` / `whiteboard_read`(内置工厂),或从 `tool_loader` 加载用户定义工具。
- `_resolve_prompt(raw, self_name)` —— 替换 `{{AGENTS}}` 为"所有其他 agent 的 name + description"。
- **CompositeBackend 路由**:若 agent 配了 skills,挂 `/skills/` → `ReadOnlyFilesystemBackend`(只读),其余走默认 backend(读写)。
- `close_agent(agent)` —— 关闭 checkpointer 连接,释放资源。

### 4.5 StreamEngine — `engine.py`(执行层"心脏")

把一个 agent 的 LangGraph 流输出转成统一 SSE 事件流。**不决定派谁**(那是 dispatch 工具的活),只负责"跑某个 agent + 翻译 chunk"。

两个入口:

- `run(session_id, prompt)` —— 跑用户直接对话的 agent(Manus / TeamLeader on team session)。流到 session 的 channel。
- `start(...)` —— 跑被 **dispatch** 的 agent(Coder/Researcher)。同样流式,**外加**:完成后把结果写 whiteboard + 通过 mailbox 通知调用方。
- `_stream(session_id, prompt, speaker)` —— 内部统一实现:`build_agent` → `agent.astream()` → `convert_chunk` → `_final_text` 提取结果 → `close_agent` → 启动 pending dispatch / 检查 inbox。

`convert_chunk` 含 `_StreamState` 去重逻辑(从旧 AGUIBridge 移植),保证 `subgraphs=True` 下的 team 流安全。

### 4.6 频道层 — `channels.py`

`ChannelRegistry`:每个 session 一个 `asyncio.Queue`。engine 往里 push 事件帧,stream 端点 drain 出来。

- `drain_single(session_id)` —— 单 session 流。
- `fan_in(scope_id, root_id)` —— 群聊流:动态展开 scope 下所有后代 session(子 agent 运行中新增也会自动并入)。每帧带 `session_id` + `speaker` 自归因。
- `drain_sessions(id_list)` —— 显式 session 集合合并。

**所有 drain 函数产出的是已格式化的 SSE 字节帧**(`data: {...}\n\n`),stream 端点原样转发 —— 不重新 frame,不重新 buffer。这是 token-by-token 流式的关键(试过 `sse-starlette` 的 `EventSourceResponse`,它会批量输出)。

### 4.7 事件协议 — `event_schema.py"

统一 SSE 事件 schema,前后端唯一契约。每事件带 `session_id` + `message_id` + `speaker`(让 fan-in 流可自归因)。

事件种类:`message_start` / `text_delta` / `thinking_delta` / `message_end` / `tool_call_start` / `tool_call_args` / `tool_call_result` / `tool_call_end` / `step_start` / `step_end` / `error` / `done`。

- `frame(event)` —— 渲染为 `data: {json}\n\n`。
- `done_sentinel(session_id)` —— **内部**流结束标记(区别于 `done` 事件: sentinel 是 channel drainer 消费的,不发给前端)。
- 流以字面量 `data: [DONE]\n\n` 收尾(所有参与 session 都 `done` 之后)。

### 4.8 Agent 间协作 — `mailbox.py` + `whiteboard.py`

- **MailboxStore** —— agent 间消息(`kind`:dispatch / result / chat)。`dispatch` 工具派活时写 mailbox + 唤醒目标 agent;agent 完成后写 result 回 mailbox 通知调用方。`wakeup handler` 处理"agent 空闲时检查 inbox"。
- **WhiteboardStore** —— 每个 scope 的共享 artifact 空间(通信层;sandbox 存真实文件)。软结构:自由内容 + 轻元数据,无强 schema。

### 4.9 配置加载器 — `agent_loader.py` / `tool_loader.py` / `skill_loader.py`

三者都从 `~/.openmanus/` 加载:

- `agent_loader` —— `agents/<Name>/{agent.yaml, prompt.md}`,`agent.yaml` 含 `name`/`description`/`tools`/`skills`/`strip_file_tools`/`sub_agents`/`allowed_tools`。`seed_builtin()` 首次复制 `backend/seed/agents/` 到此。
- `tool_loader` —— `tools/<name>/{tool.yaml, entry.py}`,用户自定义 Python 工具。
- `skill_loader` —— `skills/<name>/SKILL.md`(可含 `scripts/` + `references/` + `assets/`)。

**热更新**:agent 实例不常驻,每次 `build_agent` 重新加载 prompt + 替换占位符 → 改 agent 配置/prompt 下次对话自动生效。

### 4.10 中间件 — `middleware/`

- `ToolGuardMiddleware(excluded=...)` —— 拦截工具调用,`excluded` 集合内的直接拒。Manus 用 `excluded = _FILE_TOOLS`(所有文件工具),其他 agent 用 `excluded = {"task"}`。
- `AgentTraceMiddleware(name=...)` —— 记录 agent 执行 trace(为 L2 skill 进化预留,详见 ROADMAP)。
- `LLMTraceMiddleware` —— LLM 调用 trace。

### 4.11 工具层 — `tools/`

- `mailbox_tools.py` —— `make_dispatch_tool`(动态注入 agent 列表到 docstring)/ `make_send_message_tool` / `make_read_mailbox_tool`。
- `whiteboard_tools.py` —— `make_whiteboard_write_tool` / `make_whiteboard_read_tool`。
- `roles.py` —— 角色定义。

---

## 5. 系统架构与数据流

### 5.1 四 Agent 架构总览

```
用户消息
   │
   ▼
┌───────────┐  dispatch   ┌──────────────┐
│   Manus   │ ──────────► │   Coder      │ (read/write/edit/execute)
│ (入口路由) │             ├──────────────┤
│ tools:    │  dispatch   │  Researcher  │ (read/list/grep —— 只读)
│ dispatch  │ ──────────► ├──────────────┤
│           │  dispatch   │  TeamLeader  │ (再 dispatch + mailbox + whiteboard)
└───────────┘ ──────────► └──────────────┘
```

- Manus 是**唯一入口**(单例 `id="manus"`)。它不干活,只决定派谁。
- Coder / Researcher 是能力受限的专家(工具集按角色裁剪)。
- TeamLeader 协调多步任务:拆解 → 并行 dispatch → 等结果(自动到达,不轮询)→ 必要时再派 → 写总结。
- 所有跨 agent 通信走 mailbox;共享产物走 whiteboard。

### 5.2 请求处理流程(典型一轮)

```
1. 前端 POST /sessions/manus/messages  {content: "..."}
   └─ streams.post_message:
        ├─ cd 前缀?  → 委托 SandboxStore(独立端点,不走 agent)
        ├─ /skill?   → 注入 SKILL.md 到 prompt
        └─ 否则: asyncio.create_task(engine._stream(session_id, prompt, speaker))
   └─ 立即返回 {ok: true, session_id}  (非阻塞)

2. 前端 GET /stream?scope=<team_id>  (或 ?sessions=manus)
   └─ streams._sse_byte_stream:
        └─ fan_in(scope) / drain_single / drain_sessions
            └─ 逐帧 yield "data: {...}\n\n"

3. engine._stream(session_id, prompt, speaker):
   ├─ build_agent(session_id)  ← 从 DB 查 name+workdir, 新 checkpointer, create_deep_agent
   ├─ agent.astream(...)       ← LangGraph 流式
   ├─ convert_chunk            ← chunk → 统一事件, push 到 session 的 channel
   ├─ _final_text(agent)       ← 提取最终结果
   ├─ close_agent(agent)       ← 关 checkpointer 连接
   └─ 启动 pending dispatch / 检查 inbox
```

### 5.3 dispatch 路径的数据流

```
TeamLeader 调用 dispatch 工具(target=Coder, task="...")
   │
   ├─ mailbox 写一条 dispatch 消息
   ├─ channels 为新 Coder session 建队列
   ├─ asyncio.create_task(engine.start(coder_session_id, ...))
   │    └─ engine 跑 Coder,流式事件 push 到 Coder 的 channel
   │       (fan-in 的 TeamLeader 群聊流自动并入 Coder 的事件)
   │
   └─ TeamLeader 本轮 STOP(不轮询 read_mailbox)
        ...
   Coder 完成:
   ├─ engine.start 把结果写 whiteboard
   ├─ mailbox 给 TeamLeader 写一条 result 消息
   └─ 唤醒 TeamLeader 下一轮(自动检查 inbox)
```

### 5.4 SSE 通信机制

- **POST 触发 + GET 订阅分离** —— POST 是普通 JSON(无流式响应生命周期问题),GET 是纯 SSE 订阅。
- **原始字节帧转发** —— channel 层产出已格式化的 `data: {...}\n\n`,stream 端点用 `StreamingResponse` 原样 yield(不用 `EventSourceResponse`,它会批量)。
- **speaker-aware** —— 每帧带 `session_id` + `speaker`,fan-in 流前端按 `session_id` 拆回各参与者视图。
- **动态 fan-in** —— `fan_in(scope)` 在子 agent 运行中新增时自动展开并入。

---

## 6. 数据模型

### 6.1 双层持久化总览

| 层 | 文件 | 存什么 | 隔离键 |
|---|---|---|---|
| **消息内容层** | `checkpoints.db` | 对话历史(消息文本、工具调用) | `thread_id = session_id` |
| **会话元数据层** | `sessions.db` | 参与者注册表 + agent 间消息 + 共享 artifact | `session_id` / `scope_id` |

### 6.2 表 1:`sessions`(参与者节点)

```sql
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,      -- session_id(Manus 固定 "manus")
    kind        TEXT NOT NULL DEFAULT 'root',  -- root / team / subagent
    name        TEXT,                  -- agent 名(Manus/Coder/...)
    status      TEXT NOT NULL DEFAULT 'active',
    title       TEXT,
    model       TEXT,
    workdir     TEXT,                  -- 该 session 的 sandbox 根
    scope_id    TEXT,                  -- 所属 team 空间(NULL = 顶层)
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT,
    updated_at  TEXT
);
```

**`scope_id` 是空间归属**(回答"我在哪个房间"),不是关系拓扑("谁和谁说过话"由 mailbox 隐含)。

### 6.3 表 2:`mailboxes`(agent 间消息)

```sql
CREATE TABLE mailboxes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,     -- 收件人
    from_session_id TEXT NOT NULL,     -- 发件人
    kind            TEXT NOT NULL,     -- dispatch / result / chat
    content         TEXT,
    whiteboard_ref  TEXT,              -- 关联的 whiteboard artifact
    read            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT
);
```

> **注意**:旧架构有 `message_links` 边表,已删除。协作拓扑是 mailbox 消息的涌现属性,不存储图。

### 6.4 表 3:`whiteboard`(共享 artifact)

```sql
CREATE TABLE whiteboard (
    id          TEXT PRIMARY KEY,
    scope_id    TEXT NOT NULL,         -- 属于哪个 team 空间
    session_id  TEXT NOT NULL,         -- 创建者
    kind        TEXT,                  -- 自由分类
    title       TEXT,
    content     TEXT,                  -- 软结构,自由内容
    created_at  TEXT
);
```

### 6.5 两个抽象

| 概念 | 是什么 | 实体 |
|---|---|---|
| **session** | 一个 agent 参与者的对话流(时间线) | `sessions` 表一行 + checkpointer thread |
| **scope** | 一个 team 空间(session 的 `scope_id` 指向它) | `kind=team` 的 session |

看输出 = `(scope_id, session_id)`:
- `scope_id=null` → 只看一个 session(单 agent 1:1)
- `scope_id=team_id` → fan-in 该 scope 下所有后代 session 的流(team 群聊)

---

## 7. API 设计概览

所有路由分 6 个 router,挂载点见 `main.py:create_app()`。

### 7.1 流端点(`api/streams.py`)

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/sessions/{id}/cd` | 切 workdir(相对/绝对/`cd ..`),不走 agent |
| POST | `/sessions/{id}/messages` | 发消息 + 触发 agent run(后台非阻塞) |
| GET | `/stream?scope=<team_id>` | 群聊 fan-in SSE 流 |
| GET | `/stream?sessions=id1,id2` | 显式 session 集合 SSE 流 |
| GET | `/health` | 健康检查 |

### 7.2 会话 REST(`api/sessions.py`)

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/sessions` | 新建 session |
| GET | `/sessions` | 列表(可按 kind/scope_id 过滤) |
| GET | `/sessions/{id}` | 详情 |
| PATCH | `/sessions/{id}` | 更新元数据 |
| DELETE | `/sessions/{id}` | 删除 |
| POST | `/sessions/{id}/reset` | reset(单例 Manus = `adelete_thread`) |
| POST | `/sessions/{id}/preview` | 预览(临时 build agent 读 checkpointer) |
| GET | `/sessions/{id}/mailbox` | 收件箱 |
| GET | `/sessions/{id}/whiteboard` | 该 session 的 artifact |

### 7.3 文件操作(`api/files.py`)

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/files/tree?workdir=` | 根 + 第一层(目录折叠,带 `has_children`) |
| GET | `/files/children?path=&workdir=` | 懒加载单层子目录 |
| GET | `/files/read?path=&workdir=` | 读文件 |
| PUT | `/files/write` | 写文件 `{path, content, workdir}` |
| DELETE | `/files/delete` | 删除 `{path, workdir}` |
| POST | `/files/mkdir` | 建目录 `{path, workdir}` |
| POST | `/files/create` | 建空文件 `{path, workdir}` |
| GET | `/files/watch?workdir=` | watchdog SSE(局部刷新,200ms 防抖) |

### 7.4 Agent / Skill / Tool 配置(`api/agents.py` / `skills.py` / `tools.py`)

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/agents` | agent 列表 |
| GET | `/agents/meta/tools` | 可用工具元信息 |
| GET | `/agents/meta/skills` | 可用 skill 元信息 |
| GET | `/agents/{name}` | agent 详情 |
| POST | `/agents` | 新建 agent |
| PUT | `/agents/{name}` | 更新 agent |
| DELETE | `/agents/{name}` | 删除 agent |
| GET | `/skills` | skill 列表 |
| GET | `/skills/{name}/tree` | skill 文件树 |
| GET | `/skills/{name}/file` | 读 skill 文件 |
| GET | `/tools` | tool 列表 |
| GET | `/tools/{name}/tree` | tool 文件树 |
| GET | `/tools/{name}/file` | 读 tool 文件 |

---

## 8. 关键设计决策与约定

### 8.1 双层持久化分离

消息内容(checkpointer)和会话元数据(sessions.db)分两个 SQLite 文件。原因:checkpointer 是 LangGraph 管理的(表结构由它定),sessions 是我们自己的原生 SQL。分开避免互相干扰。

### 8.2 Agent 实例不常驻(方案 A)

agent 实例**不缓存、不跨请求**。每次 `_stream` 时 `build_agent` 新建,跑完 `close_agent` 丢弃。历史不丢(checkpointer 按 `thread_id` 隔离存 DB)。收益:无并发污染、配置热更新自然生效、无资源泄漏。详见 `PROJECT_STATUS.md` 的"Agent 生命周期重构"。

### 8.3 ToolGuardMiddleware 工具护栏

`ToolGuardMiddleware(excluded=...)` 在中间件层硬剥工具。Manus 用 `excluded = _FILE_TOOLS`(所有文件工具),保证入口路由 agent 不能直接动文件,只能 dispatch。其他 agent 用 `excluded = {"task"}`。

> **L1 规划**:这套硬规则会被**工具级权限审批 + 前端 dialog** 替代(见 ROADMAP P1)。

### 8.4 进程内 asyncio.Queue 实时分发

无消息队列中间件(Redis/RabbitMQ)。agent 间分发用进程内 `asyncio.Queue`(`channels.ChannelRegistry`)。MVP 设计,简单可靠,**但进程重启会丢失运行中的任务**(已完成的存 DB 不丢)。

### 8.5 原生 SQL 无 ORM

会话表用 `aiosqlite` 原生 SQL,无 SQLAlchemy。表少、查询简单,ORM 是过度设计。

### 8.6 src-layout 包结构

`backend/src/openmanus/` —— 标准 Python src-layout,`uv_build` 构建,`module-name = "openmanus"`。

### 8.7 自定义 SSE 事件协议(非 AG-UI)

前后端之间走**自定义 speaker-aware SSE 事件**(每帧带 `session_id` + `speaker`)。早期版本用 AG-UI 协议,因 CopilotKit 移除后不再需要标准 AG-UI,改为更贴合多 agent 群聊的自定义协议。

### 8.8 virtual_mode 文件隔离

`LocalShellBackend(virtual_mode=True)` 把文件操作限制在 workdir 内。**但 `execute()` shell 命令不受限**(deepagents 设计)—— 真正隔离需要 Docker/VM backend(L1 待办)。

### 8.9 已知问题 / TODO

- `execute()` shell 命令不受 `virtual_mode` 限制(需 Docker/VM 做真正隔离)
- seed 只首次复制,更新内置 agent prompt 需手动操作
- TeamLeader 偶发轮询 `read_mailbox`(prompt 约束强化中)
- 进程内 Queue,重启丢运行中任务

> L1 阶段完整任务清单见 [ROADMAP.md](./ROADMAP.md) §3.3。

---

## 9. 快速上手

### 环境准备

- Python 3.12+ with [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ with `yarn`

### 配置(`backend/.env`)

```bash
# Mode A:Anthropic 协议(默认,适合 GLM/Anthropic/Z.ai)
MODEL_PROVIDER=anthropic
MODEL=GLM-5.2
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic

# Mode B:OpenAI 兼容
# MODEL_PROVIDER=openai
# OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://api.openai.com/v1
# MODEL=gpt-4o-mini

# 公司内网自签证书
# SSL_VERIFY=false
```

### 启动

```bash
# 后端(端口 8999)
cd backend
uv run uvicorn openmanus.main:app --reload --port 8999

# 前端(端口 5173)
cd frontend
yarn install && yarn dev

# 或 Windows 下一键启动(含 Electron)
# 双击 restart.bat
```

### 关键端点验证

```bash
# 健康检查
curl http://127.0.0.1:8999/health
# {"status":"ok","model":"GLM-5.2","workdir":"..."}

# 发消息触发 agent
curl -X POST http://127.0.0.1:8999/sessions/manus/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "hello"}'
# {"ok":true,"session_id":"manus"}

# 订阅 SSE 流
curl -N "http://127.0.0.1:8999/stream?sessions=manus"
```

### 前端联调

打开 http://localhost:5173,vite dev proxy 自动转发 `/sessions` / `/stream` / `/files` 等到 `:8999`。

---

## 附录:代码规模

(略,以实际为准。)
