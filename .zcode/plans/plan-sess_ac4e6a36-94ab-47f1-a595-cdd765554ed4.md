## 方案 A：agent 实例不常驻，按需创建用完即丢

### 核心原则

1. **agent 实例不缓存、不常驻** — 每次 `_stream` 时按 session_id 临时 build，跑完丢弃
2. **`build_agent` 只接收 `session_id`** — name 和 workdir 从 DB 查，保证一致性
3. **cd 不碰 agent** — 只更新 session 行的 workdir，下次消息自然用新 workdir
4. **engine 是唯一 build 点** — `_stream` 内部 build agent，上层只传 session_id

### checkpointer 连接管理

每次 `build_agent` → `get_checkpointer()` → 新 aiosqlite 连接。跑完后需要关闭，否则泄漏。在 `_stream` 的 `finally` 块里关闭连接。

---

### 修改点清单（6 个文件）

#### 1. `backend/src/openmanus/agent_factory.py`

**`build_agent(name, workdir)` → `build_agent(session_id)`**

```python
async def build_agent(session_id: str) -> CompiledStateGraph:
    s = await session_store.get(session_id)
    if not s:
        raise ValueError(f"session not found: {session_id}")
    name = s["name"]
    workdir = s.get("workdir") or settings.workdir
    # ... 后续逻辑不变（model/backend/tools/skills/middleware）
```

**删除以下内容**：
- `_entry_agent_cache` 字典（line 48）
- `build_entry_agent` 函数（line 205-219）— 不再需要缓存入口 agent
- `ENTRY_AGENT = "Manus"` 常量 — 不再需要

**新增**：checkpointer 关闭辅助函数
```python
async def close_agent(agent):
    """关闭 agent 的 checkpointer 连接，释放资源。"""
    cp = getattr(agent, "checkpointer", None)
    if cp and hasattr(cp, "conn"):
        await cp.conn.close()
```

#### 2. `backend/src/openmanus/engine.py`

**`_stream` 改为内部 build agent**：

```python
async def _stream(self, *, session_id: str, prompt: str, speaker: str) -> str:
    agent = await build_agent(session_id)   # ← 内部 build
    config = {"configurable": {"thread_id": session_id}}
    try:
        # ... astream 逻辑不变
    finally:
        await close_agent(agent)            # ← 关闭连接
        # ... pending dispatch 逻辑（改为只传 session_id，不传 agent）
```

**`run` 方法**：去掉 `agent` 参数，只传 session_id
```python
async def run(self, *, session_id, prompt, speaker, mode="async"):
    if mode == "async":
        task = asyncio.create_task(self._stream(session_id=session_id, ...))
        ...
    return await self._stream(session_id=session_id, ...)
```

**`start` 方法**：去掉 `agent` 参数，只存 `target_session_id` 到 `_pending`
```python
async def start(self, *, caller_session_id, target_agent, task, scope_id, target_session_id):
    # _pending 只存 session_id，不存 agent 实例
    self._pending.setdefault(caller_session_id, []).append({
        "target_session_id": target_session_id,
        "prompt": prompt, "speaker": target_agent,
        "scope_id": scope_id, "caller_session_id": caller_session_id,
    })
```

**`_start_and_record`**：去掉 `agent` 参数
```python
async def _start_and_record(self, *, target_session_id, prompt, speaker, scope_id, caller_session_id):
    answer = await self._stream(session_id=target_session_id, prompt=prompt, speaker=speaker)
    ...
```

**`_stream` finally 块的 pending launch**：去掉 `agent=p["agent"]`
```python
task = asyncio.create_task(self._start_and_record(
    target_session_id=p["target_session_id"], ...
))
```

**`_start_turn_with_inbox`**：去掉手动 build_agent，改为调 `self.run(session_id=...)`
```python
async def _start_turn_with_inbox(self, session_id, row):
    # ... 构建 prompt
    await self.run(session_id=session_id, prompt=prompt, speaker=role, mode="async")
```

**`_final_text`**：改为接收 session_id，内部临时查
```python
async def _final_text(session_id, config):
    agent = await build_agent(session_id)
    try:
        snapshot = await agent.aget_state(config)
        ...
    finally:
        await close_agent(agent)
```
*注意：这里有优化空间 — `_stream` 已经有 agent 实例，可以把 final_text 的提取放在 close 之前。但为了简单先这样，后续优化。*

**实际优化**：在 `_stream` 里 agent close 之前就提取 final_text，避免二次 build：
```python
async def _stream(self, *, session_id, prompt, speaker) -> str:
    agent = await build_agent(session_id)
    config = {"configurable": {"thread_id": session_id}}
    try:
        async for chunk in agent.astream(...):
            ...
        # 在 close 之前提取 final text
        final = await _extract_final_text(agent, config)
    finally:
        await close_agent(agent)
        ...
    return final
```

#### 3. `backend/src/openmanus/api/streams.py`

**`post_message`**：去掉 build_agent / build_entry_agent，只传 session_id 给 engine
```python
# 之前
agent = await build_entry_agent(workdir)
asyncio.create_task(engine._stream(agent=agent, session_id=session_id, ...))

# 之后
asyncio.create_task(engine._stream(session_id=session_id, prompt=body.content, speaker=speaker))
```

**`cd_session`**：不碰 agent（当前已经是这样了，上次改过）

**`_resolve_agent`**：删除（死代码）

#### 4. `backend/src/openmanus/tools/mailbox_tools.py`

**TeamLeader dispatch**：去掉 build_agent，只传 session_id 给 engine.run
```python
# 之前
team_agent = await build_agent(target_agent, caller_workdir)
await engine.run(agent=team_agent, session_id=team_id, ...)

# 之后
await engine.run(session_id=team_id, prompt=task, speaker=target_agent, mode="async")
```

**Specialist dispatch**：去掉 build_agent，只传 session_id 给 engine.start
```python
# 之前
sub_agent = await build_agent(target_agent, caller_workdir)
await engine.start(agent=sub_agent, caller_session_id=..., ...)

# 之后
await engine.start(caller_session_id=..., target_agent=target_agent, task=task,
                   scope_id=scope_id, target_session_id=child_id)
```

**去掉 `from ..agent_factory import build_agent` import**

#### 5. `backend/src/openmanus/api/sessions.py`

**`get_messages`（line 104）**：`app.state.agent` 用于 `aget_state` 读 checkpointer 历史。改为临时 build：
```python
agent = await build_agent(session_id)
try:
    snapshot = await agent.aget_state({"configurable": {"thread_id": session_id}})
    ...
finally:
    await close_agent(agent)
```

**`reset_session`（line 248）**：同理，临时 build 来调 `adelete_thread`：
```python
agent = await build_agent(session_id)
try:
    cp = getattr(agent, "checkpointer", None)
    if cp and hasattr(cp, "adelete_thread"):
        await cp.adelete_thread(session_id)
finally:
    await close_agent(agent)
```

#### 6. `backend/src/openmanus/main.py`

**`lifespan`**：去掉 `build_entry_agent()` 和 `app.state.agent`
```python
# 之前
app.state.agent = await build_entry_agent()

# 之后：删除这行。不再需要预热 agent。
# import build_entry_agent 也可以删掉
```

---

### 不变的部分

- `build_agent` 内部的构造逻辑（model/backend/tools/skills/middleware/create_deep_agent）完全不变
- `checkpointer` 仍按 session_id（thread_id）隔离，连接同一个 DB 文件
- `LocalShellBackend(virtual_mode=True)` 不变
- `CompositeBackend` + `ReadOnlyFilesystemBackend` 不变
- 前端完全不变
- cd 的 API 和逻辑不变（只更新 session workdir）

### 风险点

1. **checkpointer 连接关闭时机** — 必须在 `_stream` finally 里 close，否则泄漏。dispatch 的 deferred 执行（`_pending`）改为存 session_id，实际 build 在 `_start_and_record → _stream` 时发生，close 也在那里。

2. **`_final_text` 二次 build** — 如果 `_stream` 内部 close 了 agent，`_final_text` 需要在 close 之前提取，或重新 build。方案是在 `_stream` 内 close 之前提取 final text。

3. **`sessions.py` 的 get_messages / reset** — 这两个 endpoint 之前用 `app.state.agent` 免费读 checkpointer。现在需要临时 build。但这两个调用不频繁（列表加载 / 重置），开销可接受。

4. **并发** — 同一个 session 的两条消息并发时，各自 build 独立 agent + 独立 checkpointer 连接。和当前行为一致（当前 dispatch 也是每次独立 build）。