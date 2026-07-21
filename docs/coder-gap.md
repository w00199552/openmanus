# Coder Agent · 对标 opencode 设计文档

> 最后更新:2026-07-21
> 范围:L1 阶段,聚焦 **Coder agent 对标 opencode coder**。
> 上游规划见 [ROADMAP.md](../ROADMAP.md);本文是 ROADMAP §3.3 "重写 Coder prompt" 与相关工具对标任务的细化设计。

> **修订说明(2026-07-21):** 初版基于"框架可能没有"的假设,低估了 deepagents 0.6.11 的能力。实际核对源码(`pip download` 后读 `middleware/filesystem.py`)后发现:`read_file`(offset/limit/多模态)、`edit_file`(replace_all + 先读约束)、`execute`(timeout)、`grep`(output_mode 三档)等能力**框架全部自带**。本文已据此大幅修正:P0 由三项收缩为两项(先读约束作废)、工具对标表重写、待确认事项核对掉 4/6。详见各章节。

---

## 0. 背景与关键发现

本文是基于一次深入对标 opencode coder(`D:\opencode`)和 deepmanus Coder 的产物。对标过程中有一个**改变方案走向的关键发现**:

> **deepagents 0.6.11 已经原生提供了我们原计划"自己造"的大部分能力** —— `FilesystemMiddleware`(权限审批 allow/deny/interrupt)、`SummarizationMiddleware`(auto-compact)、`SubAgentMiddleware`/`AsyncSubAgentMiddleware`(同步/异步子 agent)、`MemoryMiddleware`、`SkillsMiddleware`、`PatchToolCallsMiddleware`、`TodoListMiddleware`、`HumanInTheLoopMiddleware`。

**因此对标策略调整为:优先配置启用框架自带能力,而非自己造轮子。** 这大幅降低实现成本,也避免与框架对抗。

---

## 1. 架构原则(本次确认)

对标过程中确立了一条贯穿全局的架构原则:

> **两类 Agent,两种协作机制,不能混:**

| 类别 | 例子 | 协作机制 | 可见性 |
|---|---|---|---|
| **用户可见的"员工 Agent"** | Manus / Coder / Researcher / TeamLeader | **mailbox 异步消息**(员工间对话) | 用户在群聊视图可见 |
| **Agent 内置的"子 agent"** | Coder 内部的 task subagent | **deepagents `SubAgent` 配置**(同步,结果进父 context) | 用户不可见,属 Agent 内部实现 |

这条原则和 opencode 的设计不谋而合(opencode 的 `agent` 工具 spawn 的 task subagent 就是同步、只读、结果进父 context、用户不可见)。

**对 Coder 的影响:**
- Coder 可以同时具备两种协作路径:
  - 走 mailbox 派给 Researcher(员工间,异步,可见)
  - 走 `SubAgent` 内部 spawn 一个只读子 agent(内部,同步,结果直接进 Coder context)
- 两条路并存,职责清晰。

---

## 2. 工具能力对标清单

### 2.1 逐工具对比

opencode coder 内置 11 个工具 + (有 LSP 时)diagnostics + 动态 MCP。deepmanus Coder 依赖 deepagents 自带的文件工具 + `execute`。

> **重要(核对 deepagents 0.6.11 源码后修正):** deepagents 自带的 `ls` / `read_file` / `write_file` / `edit_file` / `glob` / `grep` / `execute` 这 7 个工具**能力远比初版文档评估的强,无需改进,直接用框架内置即可**。详见下方"已具备"行的实际能力。

#### 🟢 已具备 —— 直接用 deepagents 内置,不改进

| opencode 工具 | deepmanus 等价 | 框架实际能力(核对源码 `middleware/filesystem.py`) |
|---|---|---|
| **bash** | `execute` | ✅ 有 `timeout` 参数(`ExecuteSchema`,L399-402);✅ 合并 stdout/stderr + exit code;✅ prompt 教模型用绝对路径、避免 `find`/`grep`/`cat`(用专用工具) |
| **view** | `read_file` | ✅ **有 `offset`/`limit` 分页**(`ReadFileSchema`,L347-354);✅ **支持多模态**(图片/音频/视频/PDF 返回多模态块,L425-430);✅ cat -n 行号格式;✅ prompt 主动教模型分页避免 context 溢出(L416-420) |
| **edit** | `edit_file` | ✅ string replace(`old_string`/`new_string`);✅ **`replace_all` 处理多次匹配**(`EditFileSchema`,L370-373);✅ **自带"先读再改"强约束**(L437:"This tool will error if you attempt an edit without reading the file first")—— P0-3 提议自造的这个,框架已有 |
| **write** | `write_file` | ✅ 基础写文件 |
| **ls / glob / grep** | `ls` / `glob` / `grep` | ✅ grep **`output_mode` 三档**(`files_with_matches`/`content`/`count`,`GrepSchema` L389-392);✅ grep **`glob` 参数过滤文件类型**(L388);✅ glob `**`/`*`/`?` 模式 + `path` 基目录(L376-380) |

**额外能力(框架自带,opencode 反而没有):**
- **大结果驱逐到文件系统** —— 工具结果过大时不简单截断,而是 offload 到 `/large_tool_results/<tool_call_id>`,模型用 `read_file` 分页读或 `grep` 搜(L533-535)。比 opencode 的硬截断聪明。
- **多模态 read_file** —— 图片/音频/视频/PDF 直接返回多模态内容块。opencode 的 view 明确不支持图片。

#### 🔴 真正缺失(框架没有,需要自己加)

| 缺失工具 | 价值 | 说明 |
|---|---|---|
| **patch** | 大段改动省 token(Codex 风格 `*** Begin Patch` + fuzz) | 框架的 `PatchToolCallsMiddleware` 是处理 tool call 参数的,不是应用 diff 的工具,需要自己实现 |
| **fetch** | URL 抓取(text/markdown/html) | 联网基础能力,自定义 tool |
| **diagnostics** | LSP 错误反馈,opencode 最有特色的设计 | 自定义实现,被动嵌入 edit/write 响应更佳 |
| **sourcegraph** | 跨仓代码搜索(低优) | 可选,MCP 接外部 |

#### 🟡 形态不同(需要决策怎么对齐)

| 维度 | opencode | deepmanus | 决策 |
|---|---|---|---|
| **subagent 协作** | 同步阻塞,结果直接进父 context | 异步 dispatch,走 mailbox | 按架构原则(§1):**用户可见 Agent 用 mailbox 异步;Coder 内置子 agent 用 deepagents `SubAgentMiddleware` 同步**。两条路并存。 |

### 2.2 基础设施 bug

对标时发现一个**必须先修的基础设施问题**:

> **Coder 的 `agent.yaml` 里 `allowed_tools` 字段没有被 `build_agent` 链路使用。**

> ✅ **已修复(2026-07-21,P0-1 落地)。** 实际实现比原设计更进一步:不再保留 `allowed_tools` + `tools` 两个字段,而是**合并成单个 `tools` 白名单**(deepagents 内置 + OpenManus 内置 + 用户自定义都列在这里)。同时删除 `strip_file_tools`,Manus 的"无文件工具"也走同一套白名单逻辑。详见 §5.1 P0-1 的已完成标注。原 bug 描述保留如下,作为历史脉络。

代码核对结论(`agent_factory.py`):
- `allowed_tools` 在 `agent_loader.py` 加载、在 `api/agents.py` CRUD、在 `mailbox_tools.py` 展示给 Manus 看
- **但 `build_agent` 完全没用 `allowed_tools` 裁剪工具** —— 它只用了 `tools`(额外工具)+ `strip_file_tools`(Manus 专用硬剥)
- 所以 Coder 的工具边界是"deepagents 默认给全部文件工具",`allowed_tools` 只是个文档字段

这破坏了"按角色裁剪工具"的能力(Researcher 本该只读,但靠 deepagents 默认它也能拿到 write_file)。**不修这个,后续所有工具对标都建立在沙子上。**

---

## 3. 运行机制对标

| 机制 | opencode | deepmanus | 差距 | 方案 |
|---|---|---|---|---|
| **"先读再改"约束** | ✅ 强制(fileRecords 记录 readTime) | ✅ **框架 `edit_file` 自带**(L437,编辑未读文件会报错) | **无差距** | ~~P0-3 自造~~ → 作废,直接用框架 |
| **read_file 分页** | ✅ view 的 offset/limit | ✅ **框架 `read_file` 自带**(offset/limit + 多模态) | **无差距** | 用框架 |
| **execute timeout** | ✅ bash timeout 配置 | ✅ **框架 `execute` 自带**(timeout 参数) | **无差距** | 用框架 |
| **大输出处理** | ✅ 硬截断(bash 30k、glob/grep 100) | ✅ **框架更优**(驱逐到 `/large_tool_results/`,可分页读) | **框架领先** | 用框架 |
| **permission 审批** | ✅ (Tool,Action,Session,Path) 四元组 | ❌ 只有硬规则 | 明显差距 | **启用框架 `FilesystemMiddleware` + `HumanInTheLoopMiddleware`** |
| **LSP 反馈嵌入** | ✅ edit/write 响应自动带 diagnostics | ❌ 无 | 明显差距 | P2,LSP 集成时做 |
| **auto-compact** | ✅ 95% 触发 summarizer | ❌ 无 | 明显差距 | **启用框架 `SummarizationMiddleware`**(配置即用) |
| **memory/contextPaths** | ✅ CLAUDE.md 自动注入 | ❌ 无 | 明显差距 | **启用框架 `MemoryMiddleware`** |
| **subagent(同步只读)** | ✅ `agent` 工具 | ❌ 无 | 形态差距 | **启用框架 `SubAgentMiddleware`** |
| **prompt 厚度** | ✅ ~150 行约束 | ❌ 3 行 | 明显差距 | **P0 重写** |

---

## 4. opencode 值得借鉴的工程设计

这些不是"缺啥补啥",而是 opencode 在工程上做得好的地方:

1. **LSP diagnostics 嵌入工具响应** —— 模型不主动调 diagnostics 也能看到错误。比单独 diagnostics 工具更有价值。
2. **"先读再改"的 fileRecords 机制** —— 简单有效防盲改。
3. **bash 的 safeReadOnlyCommands 白名单** —— 只读命令免审批,减少打扰。deepmanus 启用 permission 时应抄。
4. **subagent 同步阻塞 + 结果进父 context** —— 对 Coder 比 mailbox 异步更轻。
5. **patch 的 fuzz 机制** —— `fuzz > 3` 拒绝,要求 context 更精确。

---

## 5. 实施方案(按优先级)

### 5.1 P0 两项(基础,必须先做)

> **P0 原为三项,核对 deepagents 源码后收缩为两项**:原 P0-3("先读再改"约束)作废 —— 框架 `edit_file` 已自带该约束(`filesystem.py` L437:"This tool will error if you attempt an edit without reading the file first")。

#### P0-1 · 修复 `allowed_tools` 生效  ✅ 已完成(2026-07-21)

> **实现与原设计的差异(重要):** 原设计是让 `allowed_tools` 真正生效、保留 `tools`+`allowed_tools` 两个字段。实际落地时,经讨论改为**合并成单个 `tools` 字段**——所有工具(deepagents 内置 / OpenManus 内置 / 用户自定义)都在 `tools` 里白名单声明,`build_agent` 对未声明的内置工具一律排除。这比原设计更干净(消除字段语义重叠),也顺带删除了 `strip_file_tools`(Manus 改用同一套白名单逻辑)。详见 `PROJECT_STATUS.md` §0 "统一工具白名单" 一节。

**目标**:`allowed_tools` 字段在 `build_agent` 链路真正裁剪工具,实现按角色限定工具集。

**当前问题**:`build_agent` 调 `create_deep_agent` 时,工具来源只有 `tools`(额外工具列表),没有对 deepagents 自带工具做白名单过滤。

**方案**(两步):
1. **核对 deepagents `create_deep_agent` 的工具裁剪参数** —— 从 graph.py 看到 `_apply_excluded_middleware` / `_ToolExclusionMiddleware`,应支持按工具名排除。
2. **在 `build_agent` 引入裁剪逻辑** —— 读 `cfg["allowed_tools"]`,转成"自带工具全集 − allowed_tools = excluded",通过框架的排除机制生效。

**改动文件**:
- `backend/src/openmanus/agent_factory.py` —— `build_agent` 计算并传 `excluded_tools`(或等价参数)给 `create_deep_agent`。

**验证**:Researcher 的 `allowed_tools` 只有只读 5 个,改完后它调 write_file 应被拒;Coder 调 write_file 正常。

**风险**:当前 `strip_file_tools`(Manus 专用)是 deepmanus 自己的 `ToolGuardMiddleware` 机制(运行时拦截),要保证改成"构造时排除"后 Manus 的 `strip_file_tools=true` 仍工作。建议统一成一套机制(`excluded_tools`),废弃 `ToolGuardMiddleware`。

---

#### P0-2 · 重写 Coder prompt

**目标**:对齐 opencode coder prompt 的编码质量约束,适配 OpenManus 多 agent 语境。

**当前问题**:Coder prompt 只有 3 行,没有任何 tone/verbosity/conventions/doing tasks/code style/proactiveness 约束。

**方案**:移植 opencode `baseAnthropicCoderPrompt` 的精华,适配点:
- "用 Agent tool 省 context" → 改成 "简单搜索用内置 task subagent,跨 agent 协作用 dispatch"(体现我们的两类协作机制)
- "不要 commit" 保留
- 路径用全路径 保留
- **"先 read 再 edit" 不用在 prompt 强调** —— 框架 `edit_file` 已强制
- 加入 OpenManus 特色:skills 用法、mailbox 协作礼仪、read_file 分页用法(框架 prompt 已教,但可强化)

**改动文件**:
- `backend/seed/agents/Coder/prompt.md` —— 重写(注意 seed 只首次复制,已部署用户需手动替换 `~/.openmanus/agents/Coder/prompt.md`,这点要在 PROJECT_STATUS 提醒)
- 同时审视 Researcher / TeamLeader / Manus 的 prompt(本批次一起做,边界清晰)

**新 prompt 结构**(移植 + 适配):
```
- 角色 + 边界(你是 Coder,只管实现,不路由不协调)
- Tone(简洁直接,不废话)
- Proactiveness(被要求才动,不surprise)
- Following conventions(先看周围代码再改)
- Doing tasks(搜索→实现→验证→lint)
- Code style(不乱加注释/版权头)
- Tool usage(独立调用合并、路径全路径、大文件用 offset/limit 分页)
- OpenManus 语境(skill 怎么用、何时 dispatch 给 Researcher、何时用内置 task)
```

---

### 5.2 P1 三项(补缺失工具)

#### P1-1 · fetch 工具(URL 抓取)

**目标**:Coder 能抓 URL 获取文档/网页。

**方案**:**自定义 tool**(deepagents 没有),用 httpx + markdown 转换库(如 `markdownify` 或 `html2text`)。对标 opencode fetch 的三档输出(text/markdown/html)。

**改动文件**:
- `backend/src/openmanus/tools/fetch_tool.py`(新建)
- 在 `agent_factory._build_tools` 里注册(作为非内置工具,按 `tools` 是否包含 `fetch` 决定)
- Coder 的 `agent.yaml` 的 `tools` 加 `fetch`

**注意**:要走 permission 审批(P2 启用后)。

---

#### P1-2 · patch 工具(统一 diff)

**目标**:大段改动省 token。

**方案**:**先核对 deepagents 是否有 patch 工具**(看到有 `PatchToolCallsMiddleware`,但那是处理 tool call 参数的,不是应用 diff 的工具)。如果没有,自定义实现,对标 opencode 的 Codex 风格 `*** Begin Patch` + fuzz 机制。

**改动文件**:
- `backend/src/openmanus/tools/patch_tool.py`(新建)—— 解析 + 应用 + fuzz 检测
- 注册方式同 fetch

**取舍**:patch 工具实现量较大(解析器 + fuzz),可考虑用现成库(如 `python-unidiff` + 自定义 apply),或先做简化版(只支持 Update 单文件)。

---

#### P1-3 · Coder 内置同步 task subagent

**目标**:Coder 内部能 spawn 一个只读子 agent 搜代码,结果直接进 Coder context(不打断自己,不走 mailbox)。

**方案**:**启用框架 `SubAgentMiddleware`** —— 这是 deepagents 原生的,配置一个 SubAgent(只读工具集)即可。

**改动文件**:
- `backend/src/openmanus/agent_factory.py` —— 给 Coder 加 `SubAgentMiddleware`,配置一个 "research" 类型的子 agent(工具集:read_file/ls/glob/grep,无 write/execute)。
- Coder prompt 补一段:"需要快速搜代码时,用 task 工具委派给内部 research 子 agent;需要跨专家协作时,用 dispatch 给 Researcher"。

**验证**:Coder 调 task 工具 → 同步阻塞跑子 agent → 结果作为 tool_result 进 Coder context → Coder 继续。

---

### 5.3 P2(框架配置即用)

这几项 ROADMAP 已列,且 **deepagents 自带中间件**,实现成本远低于预期:

| 能力 | 框架中间件 | 实现方式 |
|---|---|---|
| **auto-compact** | `SummarizationMiddleware` | `build_agent` 加该中间件,配置 token 阈值(默认 170000 或 context window 分数) |
| **memory / contextPaths** | `MemoryMiddleware` | 配置启用,对接 AGENTS.md / 项目指令文件注入 |
| **permission 审批** | `FilesystemMiddleware` + `HumanInTheLoopMiddleware` + `FilesystemPermission` | 配置 allow/deny/interrupt 规则;interrupt 模式对接前端 permission dialog(需前端 + SSE 事件扩展) |
| **LSP diagnostics** | 无框架支持 | 自定义实现(单语言优先),被动嵌入 edit/write 响应 |
| **bash 增强** | 无 | 自定义 wrapper 或中间件,加黑名单/白名单/截断/timeout |

**重要**:启用 `SummarizationMiddleware` / `MemoryMiddleware` / `FilesystemMiddleware` 后,要核对它们与现有 `ToolGuardMiddleware` / `AgentTraceMiddleware` 的共存(中间件顺序、状态字段冲突等)。

---

## 6. deepmanus 的优势(对标时保留)

对标不是单向追赶。deepmanus Coder 有 opencode 没有的:

- **Skills 一等公民** —— Coder 可挂 skills(CompositeBackend 只读挂载 `/skills/`),opencode 完全没有。
- **异步多 agent 协作** —— mailbox + TeamLeader/Researcher,opencode 只有同步 subagent。
- **server 化** —— Coder 跑后端,可被多客户端驱动。

P0/P1 改动要确保**不破坏这些优势**(尤其加同步 task subagent 时,不能让 mailbox 协作被边缘化)。

---

## 7. 执行顺序与里程碑

```
M1 编码质量基线(当前)
  ├─ P0-1 修 allowed_tools 生效          ← ✅ 已完成(合并成单个 tools 白名单)
  ├─ P0-2 重写 Coder prompt              ← 可与 P0-1 并行
  └─ 验证:Coder 真实任务质量提升,工具边界正确
  (原 P0-3 先读约束作废 —— 框架 edit_file 自带)

M2 底座补齐
  ├─ P1-1 fetch 工具
  ├─ P1-2 patch 工具
  ├─ P1-3 同步 task subagent
  └─ 验证:工具清单基本对齐 opencode

M3 L1 收口
  ├─ P2 auto-compact(框架配置)
  ├─ P2 memory(框架配置)
  ├─ P2 permission(框架 + 前端 dialog)
  ├─ P2 LSP diagnostics
  └─ 验证:L1 出口标准达成
```

---

## 8. 待确认事项(实施前需核对)

> **核对更新(2026-07-21):** 初版列了 6 项,已通过阅读 deepagents 0.6.11 源码(`/tmp/da_src/deepagents-0.6.11`)核对掉其中 4 项,剩余 2 项待 P0-1 启动时确认。

**已核对结论(写入设计):**
- ~~read_file 是否支持 offset/limit?~~ → ✅ **支持**(`ReadFileSchema` L347-354 + 多模态)。
- ~~edit_file 是否自带"先读再改"约束?~~ → ✅ **自带**(L437,P0-3 作废)。
- ~~execute 是否有 timeout?~~ → ✅ **有**(`ExecuteSchema` L399-402)。
- ~~工具输出是否截断?~~ → ✅ **有,且更优**(大结果驱逐到 `/large_tool_results/`)。

**仍待确认:**
1. **deepagents `create_deep_agent` 的工具裁剪参数具体怎么传?** —— 决定 P0-1 的实现细节(参数排除 vs 中间件拦截)。从 graph.py 看有 `_apply_excluded_middleware`,需核对调用签名。
2. **`SubAgentMiddleware` 与 deepmanus 现有 mailbox dispatch 能否共存?** —— 决定 P1-3 的集成方式(中间件顺序、状态字段冲突)。

这些在 P0-1 启动时优先核对。

---

## 附录 A · opencode coder 关键文件速查(相对 D:\opencode)

| 模块 | 文件 |
|---|---|
| Coder prompt(Anthropic/OpenAI 两版) | `internal/llm/prompt/coder.go` |
| contextPaths 注入 | `internal/llm/prompt/prompt.go` |
| 工具注册顺序 | `internal/llm/agent/tools.go` |
| Agent 主循环 / Summarize | `internal/llm/agent/agent.go` |
| subagent 工具 | `internal/llm/agent/agent-tool.go` |
| bash + 持久 shell | `internal/llm/tools/bash.go`, `shell/shell.go` |
| edit / write / view / patch | `internal/llm/tools/{edit,write,view,patch}.go` |
| glob / grep / ls | `internal/llm/tools/{glob,grep,ls}.go` |
| fetch / diagnostics | `internal/llm/tools/{fetch,diagnostics}.go` |
| fileRecords(先读再改) | `internal/llm/tools/file.go` |
| permission 服务 | `internal/permission/permission.go` |
| auto-compact 触发(95%) | `internal/tui/tui.go` |

## 附录 B · deepagents 0.6.11 自带中间件(优先复用)

| 中间件 | 能力 | 对应 opencode |
|---|---|---|
| `FilesystemMiddleware` + `FilesystemPermission` | 文件操作权限 allow/deny/interrupt | permission 审批 |
| `HumanInTheLoopMiddleware` | HITL 中断,对接 FilesystemPermission 的 interrupt | permission dialog |
| `SummarizationMiddleware` | auto-compact,token/fraction 阈值触发 | summarizer + 95% 触发 |
| `SubAgentMiddleware` / `AsyncSubAgentMiddleware` | 同步/异步子 agent | agent 工具 |
| `MemoryMiddleware` | 记忆注入 | contextPaths / OpenCode.md |
| `SkillsMiddleware` | skills(已用) | opencode 无 |
| `PatchToolCallsMiddleware` | tool call 参数 patch(非 diff 应用) | — |
| `TodoListMiddleware` | 任务清单 | opencode 无 todo 工具 |
| `RubricMiddleware` | 评分 | opencode 无 |
