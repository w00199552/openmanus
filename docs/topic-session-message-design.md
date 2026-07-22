# Topic / Session / Message / Thread 架构设计方案

> 状态:设计定稿(2026-07-22),待开发
> 上游:ROADMAP L1 基础编码平台
> 本文是 OpenManus 多 agent 架构的核心数据模型重构方案,定义 topic / session /
> message / thread 四个概念的职责、边界、数据结构和隔离规则。重构以此为基准。

---

## 0. 重构动机

当前架构存在三个核心问题:

1. **scope_id 语义模糊且可选**——只在 team 场景有意义,Manus(单例,
   scope_id=None)dispatch 时没有 scope 概念,导致单 agent 派发和 team 派发
   走两套不同的归属逻辑。
2. **session_id 同时充当 LangGraph thread_id**——session 既是"一个 agent 的
   整个生命周期"又是"checkpointer 的记忆 key",两个职责耦合,导致同一个 agent
   被多次调用时无法区分"不同的执行"。
3. **message_id 自己生成(_new_id),与 LangChain AIMessage.id 不一致**——
   实时流的 message_id 和历史回放(从 checkpoint 读)的 id 对不上,刷新页面后
   气泡 id 变化;且一次 agent run 内所有 model call 共享一个 id,导致第二次
   thinking 追加到第一次(应该独立气泡)。

本次重构定义四个清晰分层的新模型,**不做旧数据兼容**(清理旧 DB,直接写新 schema)。

---

## 1. 四个概念的定义

### 1.1 Topic(话题/群聊)

**topic = 一次任务 / 一个群聊**。它是协作的最高层容器,把"完成一次任务"涉及
的所有 agent、所有 session、所有 message、whiteboard、workdir 聚合在一起。

类比微信群:用户发起一个任务 = 建一个群(生成 topic_id),不管群里是 2 个人
(Manus + Coder)还是 4 个人(Manus + TeamLeader + Coder + Researcher),都是
同一个群。

| 属性 | 说明 |
|---|---|
| **topic_id** | 唯一标识。新建 topic 时生成的 uuid(除 "main" 固定) |
| **whiteboard** | topic 专属的任务看板(详见 whiteboard-design.md) |
| **workdir** | topic 的工作目录(可切换) |

**两个特殊的 topic:**

- **`main` topic**(topic_id 固定为 "main"):入口 agent(Manus)常驻的默认
  topic。用户和 Manus 的 1:1 对话(问候、闲聊、简单问题)都在这里。
  入口 agent 的 topic_id 不写死成 "manus",而是 "main"——为将来支持用户
  指定入口 agent 留余地(入口角色可换,但 main topic 不变)。
- **任务 topic**(topic_id = 新生成的 uuid):Manus dispatch 时新建。
  每个"真任务"(需要派给 specialist 或 team 的)是独立 topic。

**关键规则**:不管是入口 agent、单个子 agent、还是 team 多个 agent,都在对应的
topic 里。跨 topic 完全隔离(同一个 agent 在不同 topic 里互不干扰)。

### 1.2 Thread(记忆链)

**thread = 一个 agent 在一个 topic 内的记忆链**。它跨 session 延续——同一个
agent 在同一个 topic 里的多次 session(多次执行)共享 thread,有记忆延续。

| 属性 | 说明 |
|---|---|
| **thread_id** | = `f"{topic_id}:{agent_name}"`(直接算,不额外生成) |
| **粒度** | (topic_id, agent_name) |
| **用途** | LangGraph checkpointer 的隔离 key(存取对话历史) |

**隔离规则(严格):**
- 同 topic 同 agent 的多次 session → 共享 thread(有记忆)✓
- 不同 topic 的同 agent → 不同 thread(完全隔离)✓
- 跨 topic 延续记忆 → **不支持**(要在同 topic 继续)

**thread_id 的生成规则固定为 `topic_id:agent_name`**,不引入其他生成方式或
关联表,避免系统过度复杂。

### 1.3 Session(一次执行)

**session = 一个 agent 的一次完整执行(invoke/stream)**。不是"一个 agent 的
整个生命周期"——同一个 agent 在一个 topic 里可以有多个 session(多次执行)。

举例:TeamLeader 让 Researcher 搜两次天气:
```
topic 内 Researcher 的 thread:
  ├── session 1: "搜北京天气"(一次完整执行,thread 继承 → 有记忆)
  ├── session 2: "搜成都天气"(另一次执行,同 thread → 还记得搜过北京)
```

| 属性 | 说明 |
|---|---|
| **session_id** | 新生成的 uuid,每次执行新建一个 |
| **归属** | 属于一个 topic + 一个 agent |
| **记忆** | 通过 thread 继承(不直接存历史,靠 checkpointer) |
| **生命周期** | 一次 dispatch / 一次唤醒 = 新建一个 session |

**session 和 thread 的分离是本次重构的核心:**
- session_id = 标识"这是第几次执行"(新建)
- thread_id = 标识"这是谁的记忆链"(topic 内按 agent 稳定)

### 1.4 Message(一条消息)

**message = LangChain 的 AIMessage / HumanMessage / ToolMessage**(完全一致,
不自创概念)。

一次 model call 产出一条 AIMessage(里面打包了 thinking + tool_calls + content)。
message_id 直接用 LangChain message 的 id(不自己生成)。

| 属性 | 说明 |
|---|---|
| **message_id** | = LangChain message 的 id(不自己 _new_id 生成) |
| **对应** | 一次 model call = 一条 AIMessage |
| **组成** | 一条 AIMessage 含 thinking + tool_calls + content,共享一个 id |

**渲染**:session 内按 message 时间顺序平铺。

---

## 2. 层级关系

```
Topic (群聊/任务)
├── topic_id                     唯一标识(main 固定,其他 uuid)
├── whiteboard                   topic 专属看板
├── workdir                      topic 工作目录(可切换)
│
├── Thread (topic 内按 agent 隔离的记忆链)
│   │   thread_id = f"{topic_id}:{agent_name}"
│   └── Session (一次完整执行,每次 dispatch/唤醒新建)
│       │   session_id = 新生成的 uuid
│       └── Message = LangChain 的 AIMessage/HumanMessage/ToolMessage
│               message_id = LangChain 的 id
```

**完整举例**(TeamLeader 协调 Researcher + Coder):

```
Topic: topic-a3f (用户任务"调研后实现 bfs")
├── whiteboard: [pending]搜bfs资料 [finished]搜bfs资料 [in_progress]写bfs
├── workdir: /projects/bfs-task
│
├── Manus thread (topic-a3f:Manus)
│   └── session 1: 用户发"调研后实现bfs" → Manus dispatch 给 TeamLeader
│
├── TeamLeader thread (topic-a3f:TeamLeader)
│   ├── session 1: 接任务,拆分,dispatch 给 Researcher + Coder
│   │   └── messages: [thinking] [dispatch(Researcher)] [dispatch(Coder)]
│   └── session 2: 收到 Researcher + Coder 结果,汇总,回复
│       └── messages: [thinking] [text"bfs已完成,见 bfs.py"]
│
├── Researcher thread (topic-a3f:Researcher)
│   └── session 1: 搜 bfs 资料,回传结果给 TeamLeader
│       └── messages: [thinking] [tool_call(grep)] [thinking] [text"bfs是..."]
│
└── Coder thread (topic-a3f:Coder)
    └── session 1: 写 bfs.py,回传结果给 TeamLeader
        └── messages: [thinking] [tool_call(write_file)] [text"写完了"]
```

---

## 3. 数据模型

### 3.1 topics 表(新建)

```sql
CREATE TABLE IF NOT EXISTS topics (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    workdir     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

- `id`:topic_id。"main" 是固定的默认 topic(入口 agent 常驻),其他是 uuid。
- `workdir`:topic 的工作目录。可切换(用户 /cd 时更新)。
- `title`:可选,任务标题(用于 sessionList 显示)。

### 3.2 sessions 表(改:加 topic_id,去 scope_id)

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    topic_id    TEXT NOT NULL,           -- 改:原 scope_id,现必填
    kind        TEXT NOT NULL DEFAULT 'root',  -- root|team|subagent
    name        TEXT,                    -- agent name (Manus/Coder/...)
    status      TEXT NOT NULL DEFAULT 'active',  -- active|running|error
    title       TEXT,
    model       TEXT,
    workdir     TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_sessions_topic ON sessions(topic_id);
```

**变化:**
- `scope_id TEXT`(nullable)→ `topic_id TEXT NOT NULL`(必填,每次执行都有 topic)
- 不再有 `thread_id` 字段——thread_id 现算(`f"{topic_id}:{name}"`),不存储。
- `kind` 保留(root/team/subagent),用于区分 session 角色。

**thread_id 不入 sessions 表的理由**:它是 `topic_id:name` 算出来的,存了反而
可能和算出来的不一致。build_agent 时直接算即可。

### 3.3 message 存储(不变,用 LangGraph checkpointer)

message 不自己建表——直接用 LangGraph 的 checkpointer(SQLite/Postgres)。
checkpointer 按 thread_id 隔离,存的就是 LangChain 的 AIMessage/HumanMessage/
ToolMessage(每条带 LangChain 生成的 id)。

**实时流的 message_id 必须用 AIMessageChunk 的 id**(从 chunk 取),不能用
_new_id() 自己生成。这样实时流和历史回放(checkpoint 读出的 AIMessage.id)一致。

### 3.4 旧表处理(不做兼容)

- 旧的 `sessions` 表(含 scope_id):**删除重建**(用户清理 data/ 目录)。
- 旧的 `whiteboard` 表(含 scope_id/session_id):**删除重建**。
- 旧的 `mailboxes` 表:按 mailbox 新设计重建(见 mailbox 设计文档,待写)。
- 不写 migration,不做旧数据兼容。

---

## 4. config 注入(关键:session_id 和 thread_id 分离)

当前代码把 `session_id` 直接当 `thread_id` 传给 LangGraph(config["configurable"]
["thread_id"])。重构后两者分离,config 同时传两个:

```python
# engine._stream 里构造 config:
config = {
    "configurable": {
        "thread_id": f"{topic_id}:{agent_name}",  # 给 LangGraph checkpointer
        "session_id": session_id,                  # 给工具(标识当前 session)
        "topic_id": topic_id,                      # 给工具(whiteboard 等)
        "agent_name": agent_name,                  # 给工具(标识当前 agent)
    }
}
```

**工具从 config 拿值的方式改变:**

| 工具需要的 | 当前(耦合) | 重构后(分离) |
|---|---|---|
| 当前 session_id | 从 thread_id 反推(两者相等) | 从 `config["configurable"]["session_id"]` 取 |
| 当前 topic_id | 从 scope_id 反推 | 从 `config["configurable"]["topic_id"]` 取 |
| 当前 agent_name | 从 session 行查 name | 从 `config["configurable"]["agent_name"]` 取 |

涉及的函数(都要改 config 取值方式):
- `dispatch_tool._config_session_id` → 读 `session_id`
- `mailbox_tools._config_session_id` → 读 `session_id`
- `agent_factory._resolve_session_id` / `_resolve_scope_id` → 读 `session_id` / `topic_id`
- whiteboard 工具的 `session_id_fn` / `scope_id_fn` → 读 `session_id` / `topic_id`

---

## 5. Manus 入口模型(已定:方案 A)

**Manus 每次 session 新建,thread 固定。**

- 用户发消息 → 在 `main` topic 里新建一个 Manus session(新 session_id)。
- Manus 的 thread_id = `"main:Manus"`(固定,跨 session 共享记忆)。
- "新对话"按钮 = 清掉 thread `"main:Manus"` 的 checkpoint 历史(adelete_thread)。
- sessionList 显示 `main` topic(里面是 Manus 的多次 session)。

**为什么 session 新建但 thread 固定:**
- session 新建:每次用户消息是一次新的执行(渲染成独立过程,符合 session 语义)。
- thread 固定:Manus 在 main topic 里的记忆要延续(用户说"接着刚才的"能接上)。
- "新对话"清 thread:用户想重新开始时,清记忆链即可。

**ensure_manus 的改动:**
- 当前:固定 id="manus" 的单例 session。
- 重构后:不再有固定 id 的单例。`main` topic 启动时确保存在(类似 ensure_manus,
  但 ensure 的是 topic,不是 session)。每次用户消息新建一个 Manus session。

---

## 6. dispatch 行为(新模型下)

Manus dispatch 任务时(在 main topic 里):

```
1. 新建 topic(topic_id = uuid,title = 任务摘要,workdir = 继承 caller 或默认)
2. 在新 topic 里新建 target agent 的 session:
   session = session_store.create(
       topic_id=new_topic_id,
       kind="subagent", name=target_agent,
       workdir=caller_workdir,
   )
3. engine 启动该 session:
   engine.start(target_session_id, topic_id, ...)
4. (Manus 的 dispatch 工具返回,Manus session 结束)
```

TeamLeader dispatch 给 specialist 时(已在任务 topic 里):

```
1. 不新建 topic(已在 topic 里)
2. 新建 specialist 的 session(same topic_id)
3. engine 启动该 session
4. 结果通过 mailbox 回传给 TeamLeader
```

**关键区别:**
- Manus dispatch → **新建 topic**(每个任务独立 topic)
- TeamLeader dispatch → **在已有 topic 内**(不新建 topic)

---

## 7. SSE 订阅与渲染

### 7.1 订阅(后端)

- `GET /stream?topic=<topic_id>` → fan-in 该 topic 下所有 session 的事件。
- `GET /stream?sessions=id1,id2` → 订阅指定 session(兼容单 session 查看)。
- `?topic=` 和 `?sessions=` 互斥,topic 优先。

**fan_in 的 focus_session 逻辑改动:**
当前 `fan_in(scope_id, focus_session_id)` 依赖"team session 的 id == scope_id"。
重构后 topic_id ≠ 任何 session 的 id,fan_in 需要改成按 topic_id 查成员
(`session_store.list_in_topic(topic_id)`),不再有"focus_session == scope"的假设。

### 7.2 渲染(前端)

**模式 1:单 agent 派发(Manus → Coder)**

消息窗体按 message 时间顺序平铺渲染:
```
[message 1] thinking "我需要先看文件" + tool_call(ls)
[message 2] thinking "现在来写代码" + tool_call(write_file)
[message 3] text "Done, 创建了 greet.py"
```
每个 message 是一次 model call 的完整输出(thinking + tool_call + text 共享
message_id,渲染成一个块)。

**模式 2:team 模式(Manus → TeamLeader → 多 specialist)**

每个 agent 的当前 session 渲染成**实时卡片**,并排排列:
- 卡片 = modal 的缩小版,显示 message 输出,2-3 行高度,自动滚动。
- 点击卡片弹出 modal,展示该 agent 单 session 的完整 message 时间序列(平铺视图,
  同模式 1)。
- modal 打开时,背后的实时流继续更新(卡片和 modal 同步)。

后端不需要为卡片加字段——卡片是前端的渲染选择(把同一个 session 的事件流同时
渲染到小卡片和大 modal 两个视图)。后端照常发事件。

---

## 8. 前端改动(sessionList → topicList)

- **sessionList → topicList**:用户看到的列表是 topic(每个 topic = 一个任务/群聊)。
- 点击 topic 进入,看到该 topic 下的 session(s)和消息。
- `main` topic 始终在列表顶部(默认入口)。
- 前端字段重命名:`activeScopeId` → `activeTopicId`,`_scopeMembersCache` →
  `_topicMembersCache`,等等。

---

## 9. 改动清单(开发时参考)

### 后端

| 文件 | 改动 |
|---|---|
| `db.py` | 新建 topics 表;sessions 表改 scope_id→topic_id(NOT NULL),去 thread_id;重建 whiteboard_note 表;SessionStore 加 topic 相关方法 |
| `engine.py` | config 注入 topic_id/session_id/agent_name(分离 thread_id);_StreamState 的 message_id 改用 AIMessageChunk.id;start/run/_stream/_record_result 适配新模型 |
| `dispatch_tool.py` | Manus dispatch 新建 topic;TeamLeader dispatch 在已有 topic 内;config 取值改 |
| `mailbox_tools.py` | config 取值改(读 session_id 而非 thread_id) |
| `whiteboard_tool.py`(新建) | 替代 whiteboard_tools.py,按 whiteboard-design.md 实现 |
| `agent_factory.py` | build_agent 用 thread_id=f"{topic_id}:{name}";config 注入;工具工厂适配;Researcher 去 whiteboard |
| `api/streams.py` | ?scope= → ?topic=;fan_in 适配 |
| `api/sessions.py` | 历史读取用 thread_id(非 session_id);reset 用 thread_id;CRUD 适配 topic |
| `channels.py` | fan_in 按 topic_id 查成员(非 scope_id) |
| `event_schema.py` | 事件的 session_id 字段含义不变(仍是 session);可选加 topic_id |

### 前端

| 文件 | 改动 |
|---|---|
| `views/session-list.jsx` | → topicList,显示 topic |
| `views/chat-pane.jsx` | team 模式卡片+modal 渲染;scopeId → topicId |
| `runtime/agent-runtime.js` | activeScopeId → activeTopicId;_scopeMembersCache → _topicMembersCache;订阅 ?topic= |
| `runtime/stream-client.js` | ?scope= → ?topic= |
| `stores/session-store.js` | 适配 topic 模型;过滤逻辑改 |

---

## 10. 实施策略(分阶段,每阶段配测试)

### 阶段 1:数据模型 + config 注入(后端地基)
- 新建 topics 表 + sessions 表改造 + whiteboard_note 表。
- SessionStore / topic_store CRUD。
- config 注入新字段(topic_id/session_id/agent_name)。
- thread_id 算法(`f"{topic_id}:{agent_name}"`)。
- **测试**:数据层 CRUD 单测 + thread_id 计算单测。

### 阶段 2:engine + dispatch 适配(核心链路)
- engine._stream 用新 config(thread_id 分离)。
- dispatch_tool:Manus dispatch 新建 topic,TeamLeader dispatch 在已有 topic。
- message_id 改用 AIMessageChunk.id。
- **测试**:dispatch_eval(Manus→Coder 单派发)+ 离线事件流验证(message_id 一致性)。

### 阶段 3:whiteboard + mailbox(协作工具)
- whiteboard_tool.py 新建(write/update_status/read)。
- mailbox 适配新模型(待 mailbox 设计文档定稿)。
- TeamLeader prompt 教看板协议。
- **测试**:whiteboard CRUD 单测 + team 协作集成测试。

### 阶段 4:前端适配(UI)
- sessionList → topicList。
- chat-pane team 模式卡片+modal。
- 字段重命名。
- **测试**:手动验证(界面操作 + 真实任务)。

每阶段完成后:pytest 全绿 + 离线验证通过,再进下一阶段。

---

## 11. 不在本次范围

- **mailbox 详细设计**——待单独文档定稿(whiteboard 已定,mailbox 待讨论)。
- **前端 Kanban 看板渲染**——后端先做好数据模型 + 工具,前端后续。
- **跨 topic 延续记忆**——不支持(在同 topic 继续)。
- **旧数据迁移**——不做,清理重建。
- **skill 机制增强**——whiteboard 暂做 tool;skill 能拿运行时上下文是 L2/L3 的事。

---

## 附录 A:概念速查

| 概念 | 定义 | id 来源 | 持久化 | 粒度 |
|---|---|---|---|---|
| **topic** | 一次任务/群聊 | 新建时 uuid("main" 固定) | topics 表 | 任务级 |
| **thread** | topic 内 agent 的记忆链 | `f"{topic_id}:{agent_name}"` 算 | 不存储(现算) | (topic, agent) |
| **session** | 一个 agent 的一次完整执行 | 新建时 uuid | sessions 表 | 执行级 |
| **message** | = LangChain message | LangChain 生成 | checkpointer | model call 级 |

**一句话记忆**:topic 是群,thread 是群里某人的记忆,session 是某人的一次发言
过程,message 是这次发言里的每句话(每次和 LLM 交互)。

## 附录 B:决策记录

| 问题 | 讨论 | 结论 |
|---|---|---|
| scope_id 怎么重新定义 | 改成每次任务都有的群聊标识 | topic_id(替代 scope_id),含 main 默认 |
| topic 改什么名 | scope/group/task/conversation/thread | topic(topic_id) |
| Manus 入口模型 | 单例 vs 每次新建 vs 每次新 topic | 方案 A:每次 session 新建,thread 固定 "main:Manus" |
| thread_id 怎么生成 | uuid / 映射表 / 算出来 | `f"{topic_id}:{agent_name}"` 算(不引入其他方式) |
| session 和 thread 的关系 | session=生命周期 vs session=一次执行 | session=一次执行,thread=记忆链(分离) |
| 跨 topic 记忆 | 支不支持 | 不支持(同 topic 继续) |
| message_id 来源 | 自己生成 vs LangChain id | LangChain id(不自己生成) |
| message 粒度 | 一次 model call vs 更细 | 一次 model call = 一个 message(含 thinking+tool_call+text) |
| 消息渲染 | 单气泡 vs 多气泡 | 单 agent 平铺;team 模式卡片+modal |
