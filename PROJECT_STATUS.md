# OpenManus 项目记忆文档

> 最后更新：2026-07-01（统一 Session 架构大重构完成）
> 仓库：https://github.com/w00199552/deepmanus.git (main 分支)
> 这份文档是项目的"长期记忆"。每次会话开始时优先读它恢复上下文。

---

## 0. 最新重大变更：统一 Session 架构（refactor/unified-session-architecture 分支）

彻底重构了 session 架构，把"单 agent / team / team 内子 agent"三套并行管道统一为一套。
**核心隐喻：系统 = 一群 agent 参与者在一个共享空间里互相发消息（字面意义的多人聊天）。**

### 9 条架构决策
1. **看输出 = `(scope_id, session_id)` 二元组**：scope=null 看单流，scope=team 看后代合流（纯透传 fan-in，按 session_id 归位，不重排不合并）
2. **session = agent 参与者**：消息只存自己一份（单一事实源，不存两份）
3. **协作关系是图非树**：删了 message_links 表，删 parent_id；节点存 `scope_id` 表空间归属
4. **mailbox = 每个 session 一个收件箱**：agent 间通信 = 互发消息（dispatch/result/chat）；混合持久化（DB + 实时 Queue）
5. **dispatch 同步/异步 = "发任务消息后等不等"**：入口 default 默认异步，TeamLeader 按编排选择
6. **白板 = agent 间 artifact 空间**（软结构化：自由内容+轻元数据），存异步结果内容，完成消息只带引用；区别于 sandbox（真实文件）
7. **sandbox = 真实文件系统工作场地**（沿用 LocalShellBackend）
8. **协议 = 废弃 AG-UI/GROUP_MESSAGE**，统一纯 FastAPI SSE 事件 schema，所有 agent 走单一 runner
9. **前端 = assistant-ui ExternalStoreRuntime + mobx**

### 删除的旧概念/文件
- AG-UI 协议层（agui_bridge.py、ag-ui-protocol 依赖）
- message_links 表（协作图边表）
- single_runner.py + team_runner.py（两个 runner/Registry）
- dispatch_single/dispatch_task/dispatch_to_team 三个工具（统一为 dispatch + dispatch_to_team）
- ChatStore + TeamStore（双 store）→ MessagesStore（单 store）
- agentService + teamService → streamService
- GROUP_MESSAGE 自定义帧
- ChatMessages + TeamMessages → ThreadView（assistant-ui primitives）

---

## 1. 项目定位

**OpenManus** = opencode 风格的 AI 编码 Agent 克隆。

- 后端：**Python FastAPI + deepagents (LangChain/LangGraph)**，统一 SSE 事件协议
- 前端：**vite + react (JS/JSX) + mobx + tailwindcss v4 + assistant-ui (v0.14, ExternalStoreRuntime)**
- 模型：双 provider（Anthropic 协议 / OpenAI 兼容）
- 数据流：view → store (mobx) → service → backend（严格单向）
- 仓库目录：`deepagents-opencode/`（含 backend/、frontend/）

---

## 2. 核心架构（重构后）

### 2.1 统一数据模型

**两个抽象把一切串起来：**

| 概念 | 是什么 | 实体 |
|---|---|---|
| **session** | 一个 agent 参与者的对话流（时间线） | sessions 表一行 + checkpointer thread |
| **scope** | 一个 team 空间（session 的 scope_id 指向它） | team kind 的 session |

看输出 = `(scope_id, session_id)`：
- scope_id=null → 只看一个 session（单 agent 1:1）
- scope_id=team_id → fan-in 该 scope 下所有后代 session 的流（team 群聊）

**协作关系不存表**：靠 mailbox 消息涌现。TeamLeader 派 Researcher = Researcher 收件箱有 dispatch 消息；Researcher 完成写白板 + 给 TeamLeader 发 result 消息（带白板引用）。

### 2.2 三个表（sessions.db）

| 表 | 存什么 |
|---|---|
| **sessions** | 节点：id, kind(root/team/subagent), name, status, scope_id, metadata |
| **mailboxes** | agent 间消息：session_id(收件人), from_session_id, kind(dispatch/result/chat), content, whiteboard_ref |
| **whiteboard** | 共享 artifact：id, scope_id, session_id, kind(自由标签), title, content |

`checkpoints.db`（LangGraph 管理）= 消息内容层，按 thread_id=session_id 隔离。

**default 是单例**：固定 id="default"，不可删，NewChat=reset（adelete_thread）。

### 2.3 统一事件协议（event_schema.py）

废弃 AG-UI，自定 SSE 事件，每条带 `session_id` + `message_id` + `speaker`：

```
message_start / text_delta / message_end  (文本流式)
tool_call_start / tool_call_args / tool_call_result / tool_call_end  (工具)
step_start / step_end  (节点步骤)
mailbox  (agent 间消息，实时推入 channel)
error / done
```

流以 `data: [DONE]\n\n` 收尾。

### 2.4 单一 Runner（runner.py）+ Channel（channels.py）

**SessionRunner.run(agent, session_id, prompt, speaker, mode)** —— 所有 agent 走这一个：
- `convert_chunk` 带 `_StreamState` 去重（从旧 agui_bridge 提炼，这是修 team 流 bug 的关键：subgraphs=True 多层级产同 token，去重保证只发一次）
- mode="async" → 后台 task，立即返回；mode="sync" → 阻塞，返回最终文本
- **流式即最终态**，不再 aget_state 二次读 final_text（旧 team bug 根因）

**ChannelRegistry** —— 单一 registry（替代 SingleRegistry + TeamRegistry）：
- 每个 session 一个 asyncio.Queue
- `fan_in(scope_id, focus_session_id)` → 多 channel 透传合流，按到达顺序，不重排
- 同时是 mailbox 的实时推送通道（hybrid 持久化的 push 半）

**dispatch 统一原语**（runner.dispatch）：创建子 session（scope_id=team_id 或 NULL）→ mailbox 发 dispatch 消息 → runner.run 子 agent → 完成后写白板 + 给父发 result 消息。sync=await 返回文本，async=立即返回 session_id。

### 2.5 双 provider 模型切换

```python
# config.py
model_provider: str = "anthropic"  # 或 "openai"
# agent_factory._build_model 按 provider 切 ChatAnthropic / ChatOpenAI
# OpenAI 模式注入 verify=ssl_verify 的 httpx client（公司自签证书跳过）
```

### 2.6 端口
- 后端 **8999**，前端 5173，vite proxy → /sessions, /scopes, /workdir, /health → 8999

---

## 3. 后端实现现状（backend/src/openmanus/）

| 文件 | 职责                                                                                                         |
|---|------------------------------------------------------------------------------------------------------------|
| `main.py` | FastAPI app，lifespan（init_db + ensure_default + build_agents）。挂 streams/sessions/workdir 路由                |
| `config.py` | Settings（.env）：model_provider/model/key/ssl_verify/workdir/database_url/port=8999                          |
| `db.py` | sessions 表 CRUD（含 scope_id, list_in_scope）+ init_db（建表 + migration）。删了 message_links                       |
| `mailbox.py` | **MailboxStore**：agent 间消息（send/inbox/outbox/mark_read）+ 混合持久化（DB + channel pusher 注入）                     |
| `whiteboard.py` | **WhiteboardStore**：artifact CRUD（create/get/list_in_scope/list_by_author/update/delete）                   |
| `event_schema.py` | 统一 SSE 事件 schema + frame 编码 + done sentinel                                                                |
| `channels.py` | **ChannelRegistry**（单例）+ drain_single + fan_in（scope 合流）+ 注册 mailbox pusher                                |
| `runner.py` | **SessionRunner**（单例）：run（async/sync）+ dispatch + convert_chunk（带去重，修 team 流 bug）                          |
| `agent_factory.py` | 构 default + TeamLeader。build_agents/get_agent_for_workdir。挂新工具                                             |
| `store.py` | get_checkpointer：SQLite / Postgres                                                                         |
| `middleware/tool_guard.py` | **ToolGuardMiddleware**：双层禁工具（default 禁 write/edit/execute/task；TeamLeader 禁 task）                         |
| `api/streams.py` | POST /sessions/:id/messages（发消息+流式）+ GET /sessions/:id/stream（?scope 合流）+ GET /scopes/:id/stream + /health |
| `api/sessions.py` | CRUD + GET /:id（assistant-ui 兼容历史压平）+ preview + reset + GET /:id/mailbox + GET /:id/whiteboard             |
| `tools/mailbox_tools.py` | **dispatch**（统一派发，sync/async）+ dispatch_to_team + send_message + read_mailbox                              |
| `tools/whiteboard_tools.py` | whiteboard_write + whiteboard_read                                                                         |
| `tools/roles.py` | ROLES 字典（Researcher/Coder 的 prompt + allowed_tools）                                                        |

---

## 4. 前端实现现状（frontend/src/）

### 4.1 数据流（mobx view→store→service）

| 层 | 文件 | 说明 |
|---|---|---|
| view | views/Workspace.jsx | react-resizable-panels 布局（SessionList \| ChatPane \| Playground） |
| view | views/ChatPane.jsx | assistant-ui AssistantRuntimeProvider 包裹 ThreadView + ChatInput；按 scope 切单/team 视图 |
| view | views/SessionList.jsx | 微信式列表：DEFAULT/TASKS 分组（taskSessions = team + 顶层 subagent） |
| component | components/chat/ThreadView.jsx | **assistant-ui primitives 组装**（ThreadPrimitive/MessagePrimitive/useMessage），保留深色主题+DiceBear头像+工具折叠 |
| component | components/chat/ChatInput.jsx | ZCode 风格输入栏（保留，接 messages.send） |
| store | stores/MessagesStore.js | **核心**：session_id→ThreadMessage[] + 统一事件 reducer + scope 合流（activeMessages computed）+ watchLive |
| store | stores/SessionStore.js | DEFAULT_ID 单例 + rootSessions/taskSessions + bumpActivity/resetDefault/select |
| runtime | runtime/assistantRuntime.js | useExternalStoreRuntime 适配（messages/isRunning/onNew/onCancel + convertMessage） |
| service | services/streamService.js | sendMessage（POST+SSE）+ subscribe（GET EventSource，支持 scope） |
| service | services/sessionService.js | CRUD + setPreview + resetHistory |
| hook | hooks/useStore.jsx | mobx rootStore context |

### 4.2 assistant-ui 集成要点
- **v0.14 是 headless**：没有 `<Thread/>` 组件，只有 primitives（ThreadPrimitive/MessagePrimitive/ComposerPrimitive）。ThreadView.jsx 用 primitives 自己组装
- 用 `useExternalStoreRuntime` 把 MessagesStore 适配成 runtime
- 消息渲染从 `useMessage()` 读 content 数组自己渲染（绕开 MessagePartRuntime context 问题）
- speaker 从 `metadata.custom.speaker` 取，决定 DiceBear 头像 seed

### 4.3 头像系统（保留）
DiceBear adventurer，HTTP API 零依赖。Manus 专属 seed="manus-open"。subagent 用 session.id 做 seed。

### 4.4 设计系统（保留）
深色"quiet dark cinematic"，token 在 index.css `@theme`（Tailwind v4）。role-*(TeamLeader绿/Researcher蓝/Coder橙)。

---

## 5. 关键实现决策（防遗忘）

1. **mobx 渲染**：immutable index replacement（this.items[i] = {...cur}）
2. **default 单例**：id 固定，NewChat=reset
3. **派活自动切换**：MessagesStore._endTurn 后 _afterDelegation（列表 diff 找新增 session）
4. **team 流 bug 根除**：单一 convert_chunk 带 _StreamState 去重 + 流式即最终态（不再 aget_state 二次读）
5. **mailbox 混合持久化**：每条消息既写 DB 又推 channel（channel pusher 由 channels 模块注入 mailbox）
6. **scope_id 表空间归属**：team 内子 agent scope_id=team_id；顶层单派活 scope_id=NULL。taskSessions = team + (subagent 且 scope_id 为空)
7. **dispatch sync/async 统一**：底层一个 runner.run，sync=await 返回文本，async=fire-and-forget

---

## 6. 启动 / 配置

### 启动
- Windows：双击 `restart.bat`
- 手动：`cd backend && uv run uvicorn openmanus.main:app --port 8999` + `cd frontend && yarn dev`

### 模型配置（backend/.env）
Mode A（OpenAI 兼容，公司内网）: MODEL_PROVIDER=openai + 公司 key/url + SSL_VERIFY=false
Mode B（Anthropic/GLM）: MODEL_PROVIDER=anthropic + MODEL=GLM-5.2 + ANTHROPIC_BASE_URL

### 关键端点
- health: GET /health
- 发消息: POST /sessions/:id/messages（body {content}，返回 SSE）
- 看流: GET /sessions/:id/stream（?scope=team_id 合流）
- team 流: GET /scopes/:id/stream
- CRUD: /sessions（GET 支持 kind/scope_id/top_level 过滤）

---

## 7. Git 状态

- 当前分支：`refactor/unified-session-architecture`（统一架构重构）
- 旧分支 main 仍是重构前状态
- .env 在 .gitignore（API key 不泄露）
- **重构未推送**（github 网络不稳，需验证充分后合并 main 再推）

---

## 8. 已知问题 / 后续

### 重构后已验证（2026-07-01）
- ✅ 后端启动（lifespan + migration + build_agents）
- ✅ 单 agent 流式（POST /sessions/default/messages，事件 schema 正确）
- ✅ dispatch 派活（default → Researcher async，子 session 创建，scope_id 正确）
- ✅ 历史回看（get_session 扁平化为 assistant-ui 格式）
- ✅ 前端渲染（assistant-ui ThreadView + 流式回复 + 工具调用 + 历史消息）
- ✅ vite proxy（health/sessions/scopes）

### 待验证 / 后续
- ⚠️ **team 完整链路**：default → dispatch_to_team → TeamLeader → dispatch(子) → scope fan-in 合流，需真实跑一次完整 team 任务验证
- ⚠️ **mailbox/白板 UI**：后端有 GET /:id/mailbox + /:id/whiteboard，前端还没接（任务看板视图未做）
- ⚠️ **assistant-ui 视觉细节**：ThreadView 基本能用，但工具调用折叠/角色色等细节可能需调
- ⚠️ **ChatInput 的 ⚙️/@/📎 占位**：未接功能
- ⚠️ 公司环境实测（模型连接、SSL、team 完整链路）

### 待清理（重构副产物）
- backend/data/ 下的旧 message_links 表数据（migration 会 DROP，但 data/sessions.db 历史数据可能残留）
- 旧测试产物（bfs/dfs/workspace/Z 等，已在 .gitignore）
