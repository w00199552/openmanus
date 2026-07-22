# Mailbox 设计方案

> 状态:设计定稿(2026-07-23),待开发
> 上游:topic/session/message 架构重构的一部分(见 topic-session-message-design.md)
> 本文记录 mailbox(agent 间消息通信)的完整设计决策,作为开发时的参考基准。

---

## 0. 定位

Mailbox 是 **topic 内 agent 之间的消息通信系统**。一个 agent 想给另一个 agent
传话(汇报结果、请求协作、闲聊),通过 mailbox 投递消息。投递会触发收件 agent
被唤醒(如果空闲),开始一个新 session 处理消息。

**一句话**:mailbox = topic 内的 agent 间消息投递系统,投递即唤醒。

---

## 1. 设计决策(已定)

### 1.1 邮箱归属:topic 级(一张表,按 to_agent 区分)

一个 topic 有一个 mailbox(不是每个 agent 一个独立邮箱实例)。所有邮件存在
一起,靠 `to_agent` 字段区分收件人。

**为什么 topic 级不是 agent 级:**
- 概念简单:topic 有一个邮箱(像项目组一个内部邮件系统),靠收件人地址区分。
- 和 whiteboard 一致:whiteboard 是 topic 级看板,mailbox 是 topic 级邮箱。
- 查询灵活:`WHERE topic_id=?` 查整个 topic 的通信流(调试/前端时序图),
  `WHERE topic_id=? AND to_agent=?` 查某人的收件。
- 不引入"空邮箱实例"的管理负担(无需按需创建 agent 邮箱)。

### 1.2 不用 session_id,用 agent_name

邮件的核心信息是"谁发的、发给谁、内容、时间"——和 session_id 无关。
session 是一次执行(很快结束),agent 身份靠 `(topic_id, agent_name)` 标识。

**当前实现的问题**:mailbox 表用 `session_id` / `from_session_id`,session 结束
后这些 id 就没意义了。改成 `from_agent` / `to_agent`(agent_name),身份稳定,
不依赖 session 查表。

### 1.3 唤醒机制:push + pull 双保险

**不要纯轮询**(agent 定时检查邮箱,效率低)。用两种触发:

**push(投递时触发)**:
```
agent A 发邮件给 agent B → mailbox.send
  → 触发唤醒判断(agent B)
  → 如果 B 空闲(status≠running)→ 唤醒(新建 session 处理)
  → 如果 B 正在跑 → 邮件在 DB 排队,等 B 跑完
```

**pull(session 结束时检查)**:
```
agent B 的 session 跑完 → finally 检查邮箱
  → 如果有未读邮件 → 新建 session 处理
```

两个检查点覆盖:
- B 空闲时邮件到达 → push 立即唤醒
- B 忙时邮件到达(push 跳过)→ pull 在 session 结束时兜住

### 1.4 邮件触发新 session(不投递给正在跑的 session)

唤醒 = 新建一个 session 执行(不是在当前 session 开新 turn)。这符合
"session = 一次执行"的语义——邮件触发的是新的一次执行。

**串行原则**:一个 agent 在一个 topic 里不并发跑两个 session。邮件到达时如果
agent 正在跑,邮件排队,等当前 session 结束后再唤醒新 session。

### 1.5 多封邮件:一个 session 处理所有未读

session 结束时检查邮箱,把**所有**积压的未读邮件打包成一个新 session 处理
(不是每封邮件建一个 session)。

**为什么不每封一个 session:**
- 语义:唤醒 = "去查收邮箱",自然该一次看完所有未读。
- 多封邮件可能相关(Researcher 结果 + Coder 结果,TeamLeader 要一起看才能判断)。
- 效率:一次 LLM 调用 vs 多次。
- 符合串行原则:session 结束 → 查邮箱 → 一次处理所有 → 再结束。

prompt 里列出所有未读邮件:
```
你收到了以下新消息:
- from Coder: 写完了 bfs.py
- from Researcher: bfs 是广度优先搜索...

请读取并处理。
```

### 1.6 已读标记:邮件进 prompt 时立即标记

唤醒新 session 时,那些触发唤醒的邮件在构造 prompt 前立即 `mark_read`。
- 避免同一封邮件触发多次唤醒。
- 避免下次 session 检查邮箱时重复处理。

### 1.7 唤醒 prompt

```
你收到了以下新消息:
{逐条列出未读邮件: "- from {from_agent}: {content}"}

请读取并处理。
```

自然语气("收到了新消息"),不像当前的机械格式("Review and continue your work")。

---

## 2. 竞态处理(asyncio.Lock)

### 2.1 竞态风险

push(投递时唤醒判断)和 pull(session 结束检查邮箱)之间存在竞态窗口:

```
T4: session-1 finally 检查 inbox → 空
T4.5: 邮件到达 → _wakeup 读 status...
      ← 此时 status 可能还是 "running"(finally 还没改完)
      → 跳过(以为 agent 还在跑)
T5: finally 改 status → "active",返回
    → 没人再检查 inbox,邮件漏掉!
```

### 2.2 解决:asyncio.Lock

锁放 **mailbox 模块内部**(保证模块闭包,不暴露给 StreamEngine)。

**锁的粒度**:`(topic_id, agent_name)`——同一个 agent 的"投递触发唤醒"和
"session 结束检查邮箱"互斥;不同 agent 之间不互斥。

**锁保护的操作**:
- `send`(投递邮件 + 触发唤醒判断):获取锁后检查收件人状态。
- `mark_read + 读取未读 + 触发新 session`:session 结束时,获取锁后原子地
  标记已读 + 读取 + 决定是否唤醒。

**锁的生命周期**:进程内(asyncio.Lock),不持久化。进程重启时重建(不影响,
重启时没有正在跑的 session)。

**锁的存放**:MessageStore(mailbox 模块)内部维护:
```python
class MailboxStore:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}  # key = f"{topic_id}:{agent_name}"
```

---

## 3. 数据模型

### 3.1 mailboxes 表(改:用 agent_name 替代 session_id)

```sql
CREATE TABLE IF NOT EXISTS mailboxes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id        TEXT NOT NULL,          -- 归属 topic
    from_agent      TEXT NOT NULL,          -- 发件人 agent_name
    to_agent        TEXT NOT NULL,          -- 收件人 agent_name
    kind            TEXT NOT NULL,          -- chat|result|...
    content         TEXT,
    whiteboard_ref  TEXT,                   -- 关联的看板条目(可选)
    read            INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_mailbox_topic ON mailboxes(topic_id);
CREATE INDEX idx_mailbox_recipient ON mailboxes(topic_id, to_agent);
```

**变化(对比当前)**:
- `session_id` → `to_agent`(agent_name)
- `from_session_id` → `from_agent`(agent_name)
- 新增 `topic_id`(当前没有,靠 session 反查)
- `kind` / `content` / `whiteboard_ref` / `read` / `created_at` 不变。

### 3.2 旧表处理(不做兼容)

删除重建。不写 migration,不保留旧数据。

---

## 4. 模块结构

### 4.1 MailboxStore(mailbox.py)

```python
class MailboxStore:
    """topic 级 agent 间消息投递系统。

    投递(send)会触发收件人唤醒判断(push);
    session 结束时调用 check_and_drain 检查积压邮件(pull)。
    两者通过 asyncio.Lock 互斥,避免竞态。
    """

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}

    async def send(
        self, *, topic_id, from_agent, to_agent, kind, content, whiteboard_ref=None
    ) -> dict:
        """投递邮件 + 触发唤醒判断(如果收件人空闲)。
        内部加锁,保证和 check_and_drain 互斥。
        """
        ...

    async def inbox(
        self, topic_id, agent_name, unread_only=False
    ) -> list[dict]:
        """读取某 agent 的邮件(可选只读未读)。"""
        ...

    async def check_and_drain(
        self, topic_id, agent_name, on_messages: Callable
    ) -> None:
        """session 结束时调用:原子地读取未读邮件 + 标记已读 + 触发新 session。
        内部加锁,保证和 send 互斥。
        """
        ...

    def _get_lock(self, topic_id, agent_name) -> asyncio.Lock:
        key = f"{topic_id}:{agent_name}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]
```

### 4.2 工具(mailbox_tools.py)

两个工具,给需要协作的 agent 配(TeamLeader / Researcher / Coder 在 team 场景):

```python
def make_send_message_tool():
    """send_message: 给同 topic 的另一个 agent 发消息。
    消息投递后,收件人如果空闲会被唤醒(开始新 session 处理)。
    """
    ...

def make_read_mailbox_tool():
    """read_mailbox: 读取自己的邮件(可选只读未读)。
    通常不需要主动调用——有新邮件时系统会自动唤醒你处理。
    但如果你需要回顾历史邮件,可以用这个工具。
    """
    ...
```

**工具的 config 取值改**:从 `config["configurable"]["session_id"]` 拿 session_id
(用于标识当前 agent);
从 `config["configurable"]["topic_id"]` 拿 topic_id;
从 `config["configurable"]["agent_name"]` 拿 agent_name。
不再从 thread_id 反推。

---

## 5. 唤醒流程(完整时序)

```
agent A 发邮件给 agent B:

1. A 调 send_message(to_agent="B", content="...")
2. mailbox.send(topic_id, from_agent="A", to_agent="B", ...)
   ├─ 获取锁 (topic_id, "B")
   ├─ INSERT 邮件到 mailboxes 表
   ├─ 检查 B 的状态(查 B 的 session 是否 running):
   │    ├─ B 正在跑 → return(邮件在 DB,等 B session 结束时 check_and_drain)
   │    └─ B 空闲 → 触发唤醒:
   │         ├─ 读取 B 的未读邮件
   │         ├─ mark_read(标记已读)
   │         ├─ 构造 prompt("你收到了以下新消息:...")
   │         ├─ 新建 B 的 session
   │         └─ engine 启动该 session
   └─ 释放锁

agent B 的 session 结束:

3. B 的 _stream finally:
   ├─ 获取锁 (topic_id, "B")
   ├─ 改 B 的 status → active
   ├─ check_and_drain(B):
   │    ├─ 读取未读邮件
   │    ├─ 如果有:
   │    │    ├─ mark_read
   │    │    ├─ 构造 prompt
   │    │    ├─ 新建 B 的 session
   │    │    └─ engine 启动该 session
   │    └─ 如果无:结束
   └─ 释放锁
```

**锁保证**:步骤 2(投递唤醒判断)和步骤 3(session 结束检查)互斥,
不会出现"邮件在竞态窗口到达导致漏掉"。

---

## 6. 前端渲染(后续)

设计意图(本次不实现,记录供前端开发参考):

- **时序图/状态图**:后续用 react flow 把消息发送流程渲染成时序图或状态图。
  mailbox 表的 `from_agent` / `to_agent` / `created_at` 是时序图的数据源。
- **team 模式卡片**:每个 agent 卡片上可显示"收到 N 条未读消息"的角标。
- **topic 视图**:可展示该 topic 的完整通信历史(谁发了什么给谁,什么时候)。

---

## 7. 改动清单(开发时参考)

### 修改
- `db.py`:mailboxes 表改 schema(to_agent/from_agent/topic_id,去 session_id)。
- `mailbox.py`:
  - MailboxStore 的 send/inbox/mark_read 改用 (topic_id, agent_name)。
  - 新增 check_and_drain 方法(session 结束时调用)。
  - 新增 asyncio.Lock(_get_lock + send/check_and_drain 内部加锁)。
  - 唤醒逻辑从 engine._wakeup/_start_turn_with_inbox 移到 mailbox 模块
    (或 mailbox 提供 on_deliver 回调,engine 注册)。
- `engine.py`:
  - _stream finally 调 mailbox.check_and_drain(替代当前的 _start_turn_with_inbox)。
  - 去掉 _wakeup / _start_turn_with_inbox(逻辑移到 mailbox 或由 mailbox 回调触发)。
  - 唤醒时新建 session(不是在当前 session 开新 turn)。
- `mailbox_tools.py`:config 取值改(读 session_id/topic_id/agent_name)。
- `agent_factory.py`:工具工厂适配(传新的 config 解析函数)。

### 新增
- 唤醒时新建 session 的逻辑(engine 或 dispatch 模块)。

### 删除
- `engine._wakeup`(逻辑移到 mailbox 模块)。
- `engine._start_turn_with_inbox`(被 mailbox.check_and_drain + 新 session 替代)。
- `mailbox.set_wakeup_handler`(改为 mailbox 内部直接调 engine 回调,或 engine
  订阅 mailbox 事件)。

---

## 8. 不在本次范围

- 前端时序图/react flow 渲染——后续。
- 邮件优先级/排序——当前按 created_at 排,够用。
- 邮件撤回/编辑——不支持(发出即不可改)。
- 跨 topic 发邮件——不支持(不同 topic 的 agent 完全隔离)。

---

## 附录:决策记录

| 问题 | 讨论 | 结论 |
|---|---|---|
| 邮箱归属 | topic 级 vs agent 级 | topic 级(一张表,按 to_agent 区分) |
| 用什么标识 agent | session_id vs agent_name | agent_name(稳定,不依赖 session) |
| 唤醒机制 | 轮询 vs push vs push+pull | push+pull 双保险(不要纯轮询) |
| 邮件触发什么 | 投递给正在跑的 session vs 新建 session | 新建 session(符合 session=一次执行语义) |
| 串行还是并发 | agent 能否同时跑多个 session | 串行(邮件排队,等当前 session 结束) |
| 多封邮件处理 | 一个 session vs 每封一个 session | 一个 session 处理所有未读(打包) |
| 已读时机 | 何时标记 | 进 prompt 时立即标记(避免重复处理) |
| 竞态怎么处理 | 标记兜底 vs 锁 | asyncio.Lock(粒度 topic_id+agent_name) |
| 锁放哪 | StreamEngine vs mailbox | mailbox(保证模块闭包) |
| 模块名 | mailbox/channel/messages | mailbox(保持现状) |
