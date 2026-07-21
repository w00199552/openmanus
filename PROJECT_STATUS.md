# OpenManus 项目记忆文档

> 最后更新：2026-07-21
> 仓库：https://github.com/w00199552/openmanus (main 分支,GitHub 项目已由 deepmanus 改名为 openmanus)
> 本地目录:`D:\deepagents-opencode`(待重命名为 `D:\OpenManus`,因 shell 占用暂缓)
> 这份文档是项目的"长期记忆"。每次会话开始时优先读它恢复上下文。
> 长期蓝图见 [ROADMAP.md](./ROADMAP.md);架构详解见 [ARCHITECTURE.md](./ARCHITECTURE.md)。

---

## 0. 最新进展（2026-07-21)

### 统一工具白名单(P0-1 完成)

本次重构了 agent 的工具配置机制,落地了 `docs/coder-gap.md` §5.1 的 P0-1。

**核心改动:工具配置统一成单个 `tools` 字段(白名单语义)**

- **之前**:`agent.yaml` 有三个工具相关字段——`tools`(额外工具)、`allowed_tools`(白名单但未生效)、`strip_file_tools`(Manus 专用开关)。三者语义重叠且 `allowed_tools` 根本没接线,导致 Researcher 实际能调 `write_file`/`execute`(只读边界形同虚设)。
- **之后**:只剩 `tools` 一个字段。它列出该 agent 能用的**所有**工具——不管是 deepagents 内置(`read_file`/`write_file`/`execute`/...)、OpenManus 内置(`dispatch`/`mailbox`/`whiteboard_*`)、还是用户自定义。`build_agent` 对 `tools` 里没列出的 deepagents 内置工具一律排除(双层防护:框架请求层过滤 + `ToolGuardMiddleware` 执行层硬拒)。
- **删除字段**:`allowed_tools`、`strip_file_tools`(硬切换,不做向后兼容)。

**四个内置 agent 的最终 `tools` 配置:**

| Agent | tools | 含义 |
|---|---|---|
| Manus | `dispatch` | 纯路由,零文件工具 |
| Researcher | `read_file, ls, glob, grep` | 真正只读(此前是假的) |
| Coder | `read_file, write_file, edit_file, ls, glob, grep, execute` | 完整编码能力,无 `task` 子 agent(P1-3 再加) |
| TeamLeader | `dispatch, send_message, read_mailbox, whiteboard_write, whiteboard_read` | 只协调,零文件工具 |

**关键实现细节:**
- `_BUILTIN_TOOLS = {write_todos, ls, read_file, write_file, edit_file, glob, grep, execute, task}`(deepagents 0.6.11 默认注入全集,`task` 因框架自动注入 general-purpose subagent 而默认存在)。
- 新增纯函数 `_resolve_tool_whitelist(declared)` → `(kept, excluded, extras)`,把白名单拆成"保留的内置 / 排除的内置 / 待实例化的非内置"三分。`build_agent` 调用它,把 `excluded` 传给 `ToolGuardMiddleware`。
- `ToolGuardMiddleware` **保留**(框架的 `_ToolExclusionMiddleware` 只在请求层过滤,挡不住模型幻觉调用;ToolGuard 做请求层 + 执行层双保险)。只是它的 `excluded` 参数来源变了——从 `strip_file_tools` 变成白名单差集。
- 顺手修了 `agent_factory._build_tools` 里 `logger` 未定义的潜在 NameError(遇到未知工具名时会崩)。

**改动文件:**
- `backend/src/openmanus/agent_factory.py`(核心:`_BUILTIN_TOOLS` + `_resolve_tool_whitelist` + `build_agent` 白名单逻辑 + `logger` 定义)
- `backend/src/openmanus/agent_loader.py`(`load_all`/`create` 删两个字段)
- `backend/src/openmanus/api/agents.py`(`AgentSummary`/`AgentDetail` 删两个字段 + 序列化点)
- `backend/src/openmanus/tools/mailbox_tools.py`(dispatch metadata 删 `allowed_tools`)
- `backend/seed/agents/{Manus,Coder,Researcher,TeamLeader}/agent.yaml`(重写,统一用 `tools`)
- `frontend/src/views/agents-view.jsx`(删 `strip_file_tools` 徽章 + `allowed_tools` 兜底文案)
- `backend/tests/test_build_agent_tools.py`(新增,两层断言:纯函数 + 集成,全绿)

**⚠️ 已部署用户升级注意:**`~/.openmanus/agents/` 里的老副本仍是旧格式(带 `allowed_tools`/`strip_file_tools`)。`load_all` 用 `raw.get(...)` 是宽容的,残留字段不会报错,但 `strip_file_tools` 不再被读 → **Manus 会突然拿到所有文件工具**。升级前请**删除 `~/.openmanus/agents/` 重新 seed**,或手动把每个 `agent.yaml` 改成新格式(把 `allowed_tools` 里的工具名并入 `tools`,删掉 `allowed_tools` 和 `strip_file_tools`)。

---

### 文档体系重构 + 三层蓝图定稿

本次会话完成了**项目方向对齐**与**文档体系全面更新**:

1. **三层规划定稿**(详见 [ROADMAP.md](./ROADMAP.md)):
   - **L1 基础编码平台**(当前)—— 对标 opencode,保留 server 化 / 多 agent / skills / mailbox 差异化优势
   - **L2 知识管理 + skill 自学习进化** —— 对标 Hermes,llmwiki + book2skill/ctx2skill
   - **L3 Loop Engine 循环工程** —— 对标 multica + 业界 loop engineering
   - **重要纠正**:Manus 保持**纯路由**,不背 loop 编排职责(loop 入口三候选:升级 TeamLeader / 新建 loop agent / `/loop` 命令,留到 L3 决策)
   - 业界坐标已查证:Hermes(Nous)、multica-ai、LangChain loop engineering、Claude Code loop engineering

2. **文档全面重构**(本次提交):
   - 新增 `ROADMAP.md` —— 三层方案 + 演进路线(长期蓝图)
   - 重写 `README.md` —— 删除 CopilotKit 时代残留(AG-UI bridge 节),对齐当前自定义 SSE 协议 + 四 agent 架构 + 双 provider 配置
   - 重构 `ARCHITECTURE.md` —— 整体改写为与当前代码一致(删除 agui_bridge / single_runner / team_runner / message_links / per-workdir 缓存等旧架构描述;补 StreamEngine / channels / mailbox / whiteboard / scope_id / 新端点表)
   - 本文档头部更新(仓库 URL 改 openmanus、补本次进展)

3. **仓库重命名**:
   - GitHub:`deepmanus` → `openmanus`(已完成,旧 URL 走重定向)
   - 本地 git origin 已更新为 `git@github.com:w00199552/openmanus.git`
   - 本地目录 `deepagents-opencode` → `OpenManus` **暂缓**(shell 占用目录导致 rename 失败,需用户手动改名后重建 venv)

### 关键事实核对(本次重构时确认)

- **端点协议**:`POST /sessions/:id/messages` + `GET /stream?scope=|sessions=`(非 AG-UI)
- **事件协议**:自定义 speaker-aware SSE(`event_schema.py`),含 `thinking_delta`
- **Agent 生命周期**:方案 A 不常驻,`build_agent` → `_stream` → `close_agent`
- **数据表**:`sessions` + `mailboxes` + `whiteboard`(无 `message_links`)
- **配置**:双 provider(`MODEL_PROVIDER=anthropic|openai`),默认 GLM-5.2 走 Anthropic 协议

---

## 0.1 历史进展（2026-07-14 ~ 07-18）

### Agent 生命周期重构（方案 A：不常驻，按需创建用完即丢）

彻底重构了 agent 实例的生命周期管理。

**核心原则：**
1. **agent 实例不缓存、不常驻** — 每次 `_stream` 时按 session_id 临时 build，跑完 `close_agent` 丢弃
2. **`build_agent(session_id)`** — 只接收 session_id，name 和 workdir 从 DB 查，保证一致性
3. **cd 不碰 agent** — 只更新 session 行的 workdir，下次消息自然用新 workdir
4. **engine 是唯一 build 点** — `_stream` 内部 build agent，上层只传 session_id

**数据流：**
```
任何入口 (post_message / dispatch / wake-up)
  ↓ 只传 session_id
engine._stream(session_id)
  ↓
build_agent(session_id) → 从 DB 读 name+workdir → 新 checkpointer → 新 graph
  ↓
agent.astream() → 跑完 → _final_text 提取结果
  ↓
close_agent(agent) → 关闭 checkpointer 连接 → 释放资源
  ↓
启动 pending dispatch (只传 session_id) / 检查 inbox
```

**为什么不会丢上下文：** checkpointer 连接同一个 SQLite DB 文件，按 thread_id（= session_id）隔离。重建 agent 只是新建一个执行器，历史消息全在 DB 里。

**删除的旧机制：**
- `_entry_agent_cache` — 按 workdir 缓存 Manus 的字典（已删）
- `build_entry_agent(workdir)` — 缓存入口 agent 的函数（已删）
- `ENTRY_AGENT = "Manus"` 常量（已删）
- `app.state.agent` — 全局共享 agent 引用（已删）
- `post_message` 里的 `build_entry_agent` 调用（已删）
- `_resolve_agent` 死代码（已删）

### Sandbox 文件浏览器（完整功能链）

#### SandboxStore 解耦
新建 `SandboxStore`，拥有 workdir + cd + 文件 CRUD，从 AgentRuntime 剥离：
- `workdir` observable（唯一来源）
- `syncFromSession(sessionId)` — session 切换时从 session 行同步
- `cd(sessionId, path)` — POST /sessions/:id/cd + 更新 workdir
- `loadTree() / loadChildren() / loadFile() / saveFile()` — 文件操作，自动带 ?workdir= 参数
- `deletePath() / createDir() / createFile()` — 右键菜单操作
- `watchUrl` getter — watchdog SSE URL

AgentRuntime 瘦身：删除 workdir 字段 + _cd 方法，cd 委托给 SandboxStore。

#### cd 命令（独立端点，不走 agent 流）
- `POST /sessions/:id/cd` — 专用端点
- 支持相对路径（`cd src`）、`cd ..` 回退、`cd ../backend/src` 多级相对、绝对路径
- 在盘根（`D:\`）`cd ..` 停在 `D:\`，和 cmd 一致
- 前端 `agentRuntime.send()` 拦截 `cd` 前缀 → 委托 `sandbox.cd()`

#### 懒加载目录树
- 后端：`GET /files/tree` 返回根 + 第一层（目录折叠），新增 `has_children` 字段
- 后端：`GET /files/children?path=` 按需加载单层子目录
- 前端：目录默认折叠，首次展开时 fetch children，按目录缓存
- 文件操作自动带 `?workdir=` 参数（per-session sandbox）

#### watchdog 实时刷新
- 后端：`_FileWatcher` — 单目录监听，随当前 session 的 workdir 切换
  - `start(wd)`：目标变化时 re-point observer（unschedule 旧 + schedule 新）
  - `stop(q)`：带队列身份判断，过期连接不 kill 当前活跃连接
  - `virtual_mode=True` 用于文件操作限制（不影响 shell execute）
  - `Observer()` + `.daemon = True`（不能传 `Observer(daemon=True)` 会 TypeError）
- 前端：`useEffect([sandbox.workdir])` 切换 session 时自动重连 SSE
- **局部刷新**：watchdog 事件 → 提取 evt.path 的父目录 → 只 refreshDir 该目录，不重载整棵树
- **防抖**：wdPending Set 收集待刷新目录，200ms 批量 flush
- 修复了 Radix ContextMenuTrigger 包裹整棵树导致卡死的问题（改为原生 onContextMenu + createPortal）

#### 右键菜单 + Modal 确认
- 右键目录：New File / New Folder / Delete
- 右键文件：Delete
- 右键空白区：New File / New Folder
- 删除 → Radix Dialog 确认弹窗（destructive 红色按钮）
- 创建 → Radix Dialog + input（回车提交，校验空名称/路径分隔符）
- workdir 旁有 `+` dropdown（Radix Popover）快捷创建

#### 后端新增端点
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/files/tree?workdir=` | 根 + 第一层子节点（has_children） |
| GET | `/files/children?path=&workdir=` | 懒加载子目录 |
| GET | `/files/read?path=&workdir=` | 读文件 |
| PUT | `/files/write` | 写文件 `{path, content, workdir}` |
| DELETE | `/files/delete` | 删除文件/目录 `{path, workdir}` |
| POST | `/files/mkdir` | 创建目录 `{path, workdir}` |
| POST | `/files/create` | 创建空文件 `{path, workdir}` |
| GET | `/files/watch?workdir=` | watchdog SSE |

### dispatch 工具动态注入 agent 列表

**问题：** `DispatchInput` description 和 dispatch docstring 写死了 Coder/Researcher/TeamLeader，用户自定义的 agent 不在其中，Manus 不知道可以委派给它。

**修复：**
- `_build_agent_registry()` — 从 agent_loader 动态生成所有 agent 的 name + description
- dispatch 工具构造时注入到 docstring
- Manus prompt.md 用 `{{AGENTS}}` 占位符

### Manus prompt 占位符 `{{AGENTS}}`

**`_resolve_prompt(raw_prompt, self_name)`** — 加载 prompt 后替换占位符：
- `{{AGENTS}}` → 所有其他 agent 的 name + description（不含自己）

**三个需求全部满足：**
1. 单一数据源 — prompt 只从 `~/.openmanus/agents/Manus/prompt.md` 读取
2. 占位符替换 — `{{AGENTS}}` 动态查询 agent_loader，拼装 name + description
3. 热更新 — agent 实例不常驻，每次 build_agent 重新加载 prompt + 替换占位符

### 子 agent workdir 配置

`LocalShellBackend(root_dir=workdir, virtual_mode=True)` — 文件操作限制在 workdir 内：
- `ls`/`read_file`/`write_file`/`glob`/`grep` 只能看到和操作 workdir 下的文件
- `..` 路径遍历被拒绝
- `execute()` shell 命令不受 virtual_mode 限制（deepagents 设计），cwd=root_dir
- `ReadOnlyFilesystemBackend` 强制 `virtual_mode=True`（CompositeBackend 路由需要）

### 代码格式化
- 前端：prettier（4-space, doubleQuote, trailingComma=es5, LF）
- 根目录 `.editorconfig`（4-space, LF，统一 PyCharm/WebStorm）

### Agent 名称大小写统一
- agent.yaml: `Coder`/`Researcher`/`TeamLeader`/`Manus`（驼峰）
- `mailbox_tools.py` TeamLeader 判断保持 `.lower()` 容错（LLM 可能传任意大小写）
- `agent_loader.get()` 本身大小写不敏感

---

## 1. 项目定位

**OpenManus** = opencode 风格的 AI 编码 Agent 平台。

- 后端：**Python FastAPI + deepagents (LangChain/LangGraph)**
- 前端：**vite + react (JS/JSX) + mobx + tailwindcss v4**
- 桌面：**Electron**（frameless window）
- 模型：双 provider（Anthropic 协议 / OpenAI 兼容）
- 数据流：view → store (mobx) → service → backend（严格单向）
- 仓库目录：`OpenManus/`（含 backend/、frontend/、electron/）

### 核心特性
- **可配置的插件化多 Agent 平台**：Agent 是文件（YAML + prompt.md），Tool 是用户定义的 Python 文件，Skill 是 SKILL.md 文件包
- **Agent 间 dispatch**：Manus 路由 → Coder/Researcher/TeamLeader，TeamLeader 协调多专家
- **Team 群聊视图**：scope fan-in 多 session 的 SSE 流
- **Sandbox 文件浏览器**：workdir 跟随 session，watchdog 实时刷新，右键 CRUD
- **Mailbox 消息系统**：agent 间通信（dispatch/result/chat）

---

## 2. 核心架构

### 2.1 统一数据模型

**两个抽象把一切串起来：**

| 概念 | 是什么 | 实体 |
|---|---|---|
| **session** | 一个 agent 参与者的对话流（时间线） | sessions 表一行 + checkpointer thread |
| **scope** | 一个 team 空间（session 的 scope_id 指向它） | team kind 的 session |

看输出 = `(scope_id, session_id)`：
- scope_id=null → 只看一个 session（单 agent 1:1）
- scope_id=team_id → fan-in 该 scope 下所有后代 session 的流（team 群聊）

### 2.2 数据库表（sessions.db）

| 表 | 存什么 |
|---|---|
| **sessions** | id, kind(root/team/subagent), name, status, scope_id, workdir, metadata |
| **mailboxes** | agent 间消息：session_id(收件人), from_session_id, kind(dispatch/result/chat), content, whiteboard_ref |
| **whiteboard** | 共享 artifact：id, scope_id, session_id, kind, title, content |

`checkpoints.db`（LangGraph 管理）= 消息内容层，按 thread_id=session_id 隔离。

**Manus 是单例**：固定 id="manus"，不可删，"新启会话"=reset（adelete_thread）。

### 2.3 Agent 生命周期（方案 A：不常驻）

```
build_agent(session_id)
  ↓ 从 DB 查 name + workdir
  ↓ get_checkpointer() → 新 aiosqlite 连接（同一 DB 文件）
  ↓ create_deep_agent(model, prompt, tools, backend, checkpointer, ...)
  ↓ 返回 agent 实例

engine._stream(session_id)
  ↓ build_agent(session_id)
  ↓ agent.astream() → 流式输出
  ↓ _final_text(agent, config) → 提取结果
  ↓ close_agent(agent) → 关闭 checkpointer 连接
  ↓ 启动 pending dispatch / 检查 inbox
```

- agent 实例不跨请求、不跨 session、不泄漏
- cd 只改 session.workdir，下次消息自然用新值
- 修改子 agent 描述 → 下次对话自动生效（热更新）

### 2.4 统一事件协议（event_schema.py）

```
message_start / text_delta / message_end     (文本流式)
tool_call_start / tool_call_args / tool_call_result / tool_call_end  (工具)
step_start / step_end                         (节点步骤)
mailbox                                       (agent 间消息)
thinking_delta                                (推理过程)
error / done
```

流以 `data: [DONE]\n\n` 收尾。

### 2.5 前端 Store 架构

```
RootStore (stores/index.js)
  ├── sessions: SessionStore      — session 列表 + 元数据
  ├── runtime: AgentRuntime       — agent 消息流（不再碰 workdir）
  ├── sandbox: SandboxStore       — workdir + cd + 文件 CRUD（独立）
  ├── agentStore: AgentStore      — agent/skill/tool 配置 CRUD
  └── skillStore: SkillStore      — skill 列表
```

### 2.6 端口
- 后端 **8999**，前端 5173，Electron dev 加载 localhost:5173

---

## 3. 后端实现现状（backend/src/openmanus/）

| 文件 | 职责 |
|---|---|
| `main.py` | FastAPI app，lifespan（load agents/tools/skills + init_db + ensure_manus）|
| `config.py` | Settings（.env）：model_provider/model/key/ssl_verify/workdir/port=8999 |
| `db.py` | sessions 表 CRUD + ensure_manus（固定 id="manus"）|
| `agent_factory.py` | **build_agent(session_id)** + **close_agent** + **_resolve_prompt**（占位符替换）|
| `store.py` | get_checkpointer：SQLite / Postgres |
| `engine.py` | **StreamEngine**：_stream（内部 build+close）/ run / start / _start_turn_with_inbox |
| `channels.py` | ChannelRegistry + drain_single + fan_in + drain_sessions |
| `event_schema.py` | 统一 SSE 事件 schema + frame 编码 |
| `mailbox.py` | MailboxStore：agent 间消息 + wakeup handler |
| `whiteboard.py` | WhiteboardStore：artifact CRUD |
| `agent_loader.py` | 从 ~/.openmanus/agents/ 加载（YAML + prompt.md），seed builtin |
| `tool_loader.py` | 从 ~/.openmanus/tools/ 加载用户定义工具 |
| `skill_loader.py` | 从 ~/.openmanus/skills/ 加载 SKILL.md |
| `readonly_backend.py` | ReadOnlyFilesystemBackend（virtual_mode=True）|
| `chat_model.py` | ChatGLM — 保留 reasoning_content |
| `api/streams.py` | POST /sessions/:id/messages + cd + GET /stream + /health |
| `api/sessions.py` | CRUD + messages（临时 build agent 读 checkpointer）+ reset + mailbox + whiteboard |
| `api/files.py` | 文件 CRUD + watchdog SSE（_FileWatcher 单目录监听）|
| `api/agents.py` | agent/skill/tool 配置 CRUD（Pydantic models）|
| `api/skills.py` | skill 列表 + 文件树 |
| `api/tools.py` | tool 文件浏览 |
| `tools/mailbox_tools.py` | dispatch（动态注入 agent 列表）+ send_message + read_mailbox |
| `tools/whiteboard_tools.py` | whiteboard_write + whiteboard_read |
| `middleware/tool_guard.py` | ToolGuardMiddleware（Manus 禁文件工具）|
| `middleware/agent_trace.py` | AgentTraceMiddleware |

---

## 4. 前端实现现状（frontend/src/）

### 4.1 数据流（mobx）

| 层 | 文件 | 说明 |
|---|---|---|
| view | views/Workspace.jsx | react-resizable-panels 布局（SessionList \| ChatPane \| Playground）|
| view | views/ChatPane.jsx | 聊天面板，按 scope 切单/team 视图 |
| view | views/SessionList.jsx | session 列表 |
| view | views/Playground.jsx | Sandbox 文件树 + 内容编辑器 |
| view | views/AgentsView.jsx | Agent 配置页面 |
| component | components/chat/ThreadView.jsx | 消息渲染 |
| component | components/chat/ChatInput.jsx | 输入栏 + /skill 命令 |
| component | components/sandbox/ConfirmDialog.jsx | Radix Dialog 确认弹窗 |
| component | components/ui/dialog.jsx | Radix Dialog 封装 |
| store | stores/SandboxStore.js | workdir + cd + 文件 CRUD |
| store | stores/AgentRuntime.js | agent 消息流（不再碰 workdir）|
| store | stores/SessionStore.js | session 列表管理 |
| runtime | runtime/eventReducer.js | 纯函数事件 reducer（14 个单元测试）|
| runtime | runtime/messageStore.js | mobx observable messagesBySession |
| runtime | runtime/streamClient.js | SSE EventSource 管理 |

### 4.2 Sandbox 文件浏览器
- 懒加载目录树（第一层折叠，点击展开动态加载）
- watchdog SSE 实时刷新（局部刷新，只更新变更文件的父目录）
- workdir 跟随 session 切换
- 右键菜单（原生 onContextMenu + createPortal）+ Radix Dialog 确认
- cd 命令（独立端点，支持相对路径 + cd .. 回退）

### 4.3 Electron 桌面客户端
- frameless window（`frame: false`）
- IPC 窗口控制（minimize/maximize/close）
- dev 模式加载 localhost:5173（openDevTools 暂时注释）

---

## 5. ~/.openmanus/ 目录结构

```
~/.openmanus/
  agents/           — 每个 agent 一个目录
    Manus/
      agent.yaml    — name, description, tools, skills, sub_agents
                      (tools 是统一工具白名单:deepagents 内置 + OpenManus 内置 + 用户自定义)
      prompt.md     — 系统提示词（支持 {{AGENTS}} 占位符）
    TeamLeader/
    Coder/
    Researcher/
  tools/            — 用户定义工具
    tool.yaml + entry.py
  skills/           — SKILL.md 文件包
    SKILL.md + scripts/ + references/ + assets/
```

---

## 6. 启动 / 配置

### 启动
- Windows：双击 `restart.bat`
- 手动：`cd backend && uv run uvicorn openmanus.main:app --port 8999` + `cd frontend && yarn dev`

### 模型配置（backend/.env）
- Mode A（OpenAI 兼容，公司内网）: `MODEL_PROVIDER=openai` + 公司 key/url + `SSL_VERIFY=false`
- Mode B（Anthropic/GLM）: `MODEL_PROVIDER=anthropic` + `MODEL=GLM-5.2` + `ANTHROPIC_BASE_URL`

### seed 机制
- 首次运行时 `seed_builtin()` 把 `backend/seed/agents/` 复制到 `~/.openmanus/agents/`
- 之后不再覆盖（用户自定义的 prompt 不被破坏）
- 更新内置 agent prompt 需手动替换 `~/.openmanus/agents/Manus/prompt.md`

---

## 7. 待办事项

### 功能
- [ ] TeamLeader 偶发轮询 `read_mailbox` — prompt 约束强化
- [ ] 消息自动滚动偶尔失效
- [ ] SubAgent 配置 Tab（agent.yaml `sub_agents` 字段）
- [ ] Human-in-loop / Interrupt Tab
- [ ] 聊天面板折叠/展开
- [ ] Tool/Skill 创建/安装顶层页面
- [ ] 后端 sandbox 配置（Embedded python312 + sandbox backend）

### 已知问题
- `execute()` shell 命令不受 virtual_mode 限制（deepagents 设计，需 Docker/VM 后端做真正隔离）
- seed 只首次复制，更新内置 agent prompt 需手动操作
