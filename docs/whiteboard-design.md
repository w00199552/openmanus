# Whiteboard 设计方案

> 状态:设计定稿(2026-07-22),待开发
> 上游:topic/session/message 架构重构的一部分
> 本文记录 whiteboard 的完整设计决策,作为开发时的参考基准。

---

## 0. 定位

Whiteboard 是 **TeamLeader 用的任务看板**。它把多 agent 协作过程结构化:
TeamLeader 接收任务后拆分,在看板上建条目跟踪;执行过程中条目状态流转,
让协作进度可视化、可追踪。

**一句话**:whiteboard = topic 内的任务看板,TeamLeader 用它拆任务、派任务、
跟踪状态。

---

## 1. 设计决策(已定)

### 1.1 数据模型:单表,直接挂 topic_id

不建独立的 whiteboard 容器表(白板与 topic 是 1:1,容器表没有独立属性)。
看板条目(note)直接关联 `topic_id`。

```
whiteboard_note 表:
  note_id      TEXT PRIMARY KEY
  topic_id     TEXT NOT NULL          — 归属的 topic(= 看板)
  author       TEXT NOT NULL          — 创建者 agent_name(如 "TeamLeader")
  kind         TEXT                    — 自由标签(research/plan/result/...)
  status       TEXT NOT NULL DEFAULT 'pending'
  title        TEXT                    — 简短标题
  content      TEXT                    — 详细内容(自由文本或 JSON)
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
```

索引:
```
CREATE INDEX idx_whiteboard_topic ON whiteboard_note(topic_id)
```

### 1.2 状态字段(status)

四种状态,构成任务的状态机:

| 状态 | 语义 | 谁改成这个状态 |
|---|---|---|
| `pending` | 任务已建,待开始 | TeamLeader 建条目时的默认状态 |
| `in_progress` | 正在执行 | 执行 agent 开始干时 |
| `finished` | 已完成 | 执行 agent 完成时 |
| `error` | 失败 | 执行 agent 失败时 |

状态流转(非强制约束,只是推荐):
```
pending → in_progress → finished
                    └→ error
```

### 1.3 扁平结构,无层级

不设 `parent_id`。所有条目平级。"子任务"靠 title/kind 描述,前端不渲染层级树。
(简单优先;未来需要层级时再加 parent_id 字段。)

### 1.4 使用范围:暂时只 TeamLeader

**只有 TeamLeader 配 whiteboard 工具**。理由:
- TeamLeader 是内置 agent,prompt 我们能控制,能教它看板协议。
- 子 agent(Coder/Researcher)不碰看板,避免给用户自定义 agent 增加看板协议门槛。
- Researcher 之前加的 whiteboard_read/write 工具要**拿掉**,回到纯只读调研。
- Researcher 的结果回传走 mailbox(给 TeamLeader 发邮件)。

### 1.5 实现方式:tool(不做 skill)

whiteboard 的操作做成 **LangChain BaseTool**(和 dispatch/mailbox 一样),
不做成 skill。

**为什么是 tool 不是 skill:**
- tool 在 agent 进程内,能直接从 `RunnableConfig` 拿运行时上下文(topic_id、
  agent_name),能 import store 访问 DB。
- skill 的 scripts 是独立脚本(通过 execute 跑),拿不到运行时上下文
  (topic_id 在 config 里,scripts 无法访问)。这是硬伤。
- 未来如果要让 whiteboard 用户可扩展(skill 化),需要增强 skill 机制
  (注入环境变量 + 客户端库),属于 L2/L3 的事。

**方法论(什么时候建条目/改状态)写进 TeamLeader prompt**,不单独抽 skill。
当前 prompt 够用;未来方法论复杂时再抽。

---

## 2. 工具定义

三个工具,只给 TeamLeader 配(`agent.yaml` 的 tools 字段):

### 2.1 whiteboard_write — 创建条目

```python
class WhiteboardWriteInput(BaseModel):
    title: str        — 简短标题
    content: str      — 详细内容
    kind: str = "task" — 自由标签(task/research/plan/result/...)
    # status 默认 pending,创建时不传

async def whiteboard_write(title, content, kind, config):
    """在 topic 的看板上创建一条任务条目(状态默认 pending)。
    用于:TeamLeader 拆分任务时,为每个子任务建一条。
    """
    topic_id = _resolve_topic_id(config)   # 从 config 拿当前 topic
    author = _resolve_agent_name(config)    # 从 config 拿当前 agent
    note = await whiteboard_store.create(
        topic_id=topic_id, author=author,
        kind=kind, status="pending",
        title=title, content=content,
    )
    return f"在看板建了条目 {note['id'][:8]} [pending]: {title}"
```

### 2.2 whiteboard_update_status — 改状态

```python
class WhiteboardUpdateStatusInput(BaseModel):
    note_id: str
    status: Literal["pending", "in_progress", "finished", "error"]

async def whiteboard_update_status(note_id, status, config):
    """更新一条看板条目的状态。
    用于:开始执行时改 in_progress,完成时改 finished,失败改 error。
    """
    topic_id = _resolve_topic_id(config)
    await whiteboard_store.update_status(
        note_id=note_id, topic_id=topic_id, status=status,
    )
    return f"条目 {note_id[:8]} 状态改为 {status}"
```

### 2.3 whiteboard_read — 读看板

```python
class WhiteboardReadInput(BaseModel):
    note_id: str | None = None     — 指定条目 id 读详情;None 列表
    status: str | None = None      — 按状态过滤(pending/in_progress/...)

async def whiteboard_read(note_id, status, config):
    """读看板条目:指定 id 读详情;不指定则列全部(可按状态过滤)。
    """
    topic_id = _resolve_topic_id(config)
    if note_id:
        note = await whiteboard_store.get(note_id)
        return f"条目 {note_id}: [{note['status']}] {note['title']}\n{note['content']}"
    notes = await whiteboard_store.list_in_topic(topic_id, status=status)
    if not notes:
        return "看板为空。"
    lines = [f"- {n['id'][:8]} [{n['status']}] ({n['author']}) {n['title']}" for n in notes]
    return "看板条目:\n" + "\n".join(lines)
```

---

## 3. TeamLeader prompt 里的看板协议

TeamLeader 的 prompt 要教它看板协作流程(这是设计意图,prompt 内容待 P0-2
TeamLeader prompt 补强时写)。大致结构:

```
## 看板协作

接收到任务后:
1. 拆分成子任务,每个用 whiteboard_write 建一条条目(pending)。
2. dispatch 每个子任务给对应 agent。
3. 子 agent 跑完发回结果(mailbox)后,把对应条目改 finished。
4. 如果有子任务失败,改 error,决定是否重派。
5. 所有条目 finished 后,给用户最终总结。
```

---

## 4. 前端渲染(后续)

设计意图(本次不实现,记录供前端开发参考):

- 在 topic 视图里展示看板,按状态分列(Kanban 风格):
  ```
  | pending      | in_progress  | finished     | error       |
  |------------- |------------- |------------- |------------- |
  | [Researcher] | [Coder]      | [Researcher] | [Coder]     |
  | 搜天气        | 写 bfs        | 搜资料(完成)  | 跑测试(失败) |
  ```
- 条目卡片显示:author、title、状态。
- 点击条目展开 content 详情。

---

## 5. 改动清单(开发时参考)

### 新增
- `whiteboard_note` 表(db.py 的 schema + WhiteboardStore)
- `tools/whiteboard_tool.py`(三个工具:write/update_status/read)

### 修改
- `db.py`:whiteboard 表结构从 `scope_id` 改 `topic_id`,加 `status` 字段,
  `session_id` 改 `author`(agent_name)。
- `agent_factory.py`:
  - TeamLeader 的 whiteboard 工具改用新工厂函数。
  - Researcher 的 tools 删掉 whiteboard_read/whiteboard_write。
- `seed/agents/TeamLeader/agent.yaml`:tools 字段更新(新工具名)。

### 删除
- `tools/whiteboard_tools.py`(旧实现,被新 whiteboard_tool.py 替代)。

### 不改
- `event_schema.py`:看板更新目前走 mailbox 事件通知(或新增 whiteboard 事件,
  待定——看前端是否需要实时推送看板变化)。

---

## 6. 不在本次范围

- 看板条目的层级(parent_id)——未来需要时加。
- whiteboard skill 化(用户可扩展)——需要增强 skill 机制,L2/L3 的事。
- 前端 Kanban 渲染——本次只做后端工具 + 数据模型,前端后续。
- 子 agent(Coder/Researcher)用看板——暂时只 TeamLeader。

---

## 附录:决策记录

| 问题 | 讨论 | 结论 |
|---|---|---|
| 拆不拆容器表 | 白板与 topic 1:1,容器表无独立属性 | 不拆,note 直接挂 topic_id |
| 加不加状态 | 升级成任务看板,要跟踪进度 | 加 status(pending/in_progress/finished/error) |
| 层级结构 | TeamLeader 建任务,Coder 建子任务? | 扁平,无 parent_id(简单优先) |
| 谁用看板 | 只 TeamLeader 还是所有 agent? | 只 TeamLeader(避免用户自定义 agent 门槛) |
| tool 还是 skill | skill 有 scripts 能执行代码 | tool(skill 的 scripts 拿不到运行时 topic_id) |
