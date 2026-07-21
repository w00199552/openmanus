# OpenManus · 三层方案与演进路线

> 最后更新:2026-07-21
> 仓库:`OpenManus`(GitHub:`w00199552/openmanus`,本地目录:`D:\OpenManus`)
> 本文是 OpenManus 的**长期蓝图**。所有阶段性工作(任务清单、优先级、里程碑)以本文为准。
> 当前架构细节见 [`ARCHITECTURE.md`](./ARCHITECTURE.md);项目进展记忆见 [`PROJECT_STATUS.md`](./PROJECT_STATUS.md)。

---

## 0. 一句话定位

**OpenManus = 可进化的多 Agent 编码平台**。

不做又一个单机 CLI coding agent。目标是构建一个**三层叠加**的系统:

- 底层是坚实的编码能力(对标 opencode,保留 server 化/多 agent/skills 的差异化优势);
- 中层是知识管理与 skill 自学习进化(对标 Hermes);
- 顶层是基于 agent 与中间件的循环工程脚手架(对标 multica + 业界 loop engineering 实践)。

每一层都建立在下一层之上,不跳层、不偷工。

---

## 1. 三层总览

```
┌──────────────────────────────────────────────────────────────┐
│  L3  Loop Engine · 循环工程                                   │
│      ── 代码开发 loop:  设计 → 编码 → 测试 → 审查 → 修复 → …  │
│      ── 黑盒测试 loop:  测试设计 → 测试执行 → 测试分析 → …    │
│      ── 基于 agent + 中间件构建的可复用 loop 模板/脚手架       │
│      ── loop 模板的抽象形式待 L3 启动时定(声明式 / 命令式)   │
├──────────────────────────────────────────────────────────────┤
│  L2  知识管理 · Skill 自学习进化                              │
│      ── llmwiki(知识库,semantic memory)                    │
│      ── book2skill / ctx2skill(skill 自动生成与进化)         │
│      ── 三层 memory(working / episodic / semantic)          │
│      ── 对标:Nous Research Hermes                            │
├──────────────────────────────────────────────────────────────┤
│  L1  基础编码平台                                             │
│      ── 核心 agent(Manus / Coder / Researcher / TeamLeader)  │
│      ── 开放 agent / skill / tool / memory 定义               │
│      ── 底座能力对标 opencode                                 │
│      ── 保留差异化:server 化 / 可配置多 agent / skills / mailbox │
└──────────────────────────────────────────────────────────────┘
```

**层间依赖关系:** L3 消费 L2 的 skill 复合与 L1 的 agent 定义;L2 建立在 L1 的 skill/agent/memory 基础设施之上。**L1 必须先打牢,L2/L3 才不会是空中楼阁。**

**当前所处阶段:L1。**

---

## 2. 业界坐标

每一层都有明确的对标对象,避免闭门造车。

### L1 · 基础编码平台 — 对标 opencode

| 能力 | opencode 现状 | OpenManus 当前 | L1 目标 |
|---|---|---|---|
| 多 Provider + 角色分模型 | ✅ 10+ provider,coder/summarizer/task/title 分模型 | ⚠️ 仅 2 档(anthropic / openai 兼容),全局单模型 | 补齐 provider 抽象 + 隐藏 agent 用便宜模型 |
| 工具级权限审批 | ✅ Grant/GrantPersistent/Deny + 弹窗 | ❌ 只有 ToolGuardMiddleware 硬规则 | 补齐工具级审批 + 前端 dialog |
| MCP Client | ✅ stdio + sse 两种 transport | ❌ 无 | 补齐 MCP client,工具自动注入 + 走权限审批 |
| LSP diagnostics | ✅ 深度集成,diagnostics 作为工具 | ❌ 无 | 补齐单语言 diagnostics 工具(先 python/ts) |
| 文件版本历史 | ✅ history.Service 快照 + diff/回滚 | ❌ 无(仅 watchdog 实时刷新) | 补齐 edit/write 前快照 + undo/rollback |
| Auto-compact | ✅ 95% 阈值摘要 + 续接 | ❌ 无 | 补齐 summarizer 隐藏 agent + engine 触发 |
| AGENTS.md / memory | ✅ contextPaths 注入 | ❌ 无 | **L1 做分层 memory 数据模型,为 L2 预留** |
| Markdown slash 命令 | ✅ `.md` + `$PARAM` | ⚠️ 仅 `/skill` | 补齐通用 markdown 命令系统 |

### L1 · 差异化优势(保留,不向 opencode 看齐)

这些是 OpenManus 的路线优势,opencode 没有,L1 阶段要**巩固**而不是弱化:

- **Server 化 / 可嵌入** — FastAPI + 自定义 SSE 事件协议,天然支持多客户端、远程、嵌入式场景。opencode 是孤岛进程,这是结构性代差。
- **可配置多 Agent** — agent = 文件(YAML + prompt.md),热更新,`{{AGENTS}}` 动态注入。opencode 的 agent 硬编码 4 种。
- **Agent 间协作基础设施** — Mailbox(dispatch/result/chat) + Whiteboard(共享 artifact) + scope fan-in 群聊视图。opencode 只有单向 subagent。
- **Skills 一等公民** — SKILL.md 文件包 + CompositeBackend 只读挂载。opencode 完全没有。
- **Sandbox 文件浏览器** — 懒加载树 + watchdog SSE + 右键 CRUD,接近 IDE 体验。

### L2 · 知识管理 + Skill 进化 — 对标 Hermes

[ Nous Research Hermes ](https://hermes-agent.nousresearch.com/docs/) 是 L2 最精确的对标:它是"self-improving agent + 三层 memory + self-evolving skills"。

| Hermes 能力 | 对应 OpenManus 规划 | 启示 |
|---|---|---|
| 三层 memory(working / episodic / semantic) | llmwiki + memory 分层 | **memory 必须分层**,不能单一 storage |
| Self-evolving skills(从执行 trace 进化 skill) | ctx2skill | skill 进化的输入是**执行 trace**,不是人写 |
| DSPy + GEPA 优化(无 GPU,纯 API) | skill 自学习引擎 | 不造优化器,借鉴 DSPy/GEPA |
| Skills vs Memory 分工(memory 存事实,skill 存过程) | 已有 skill_loader | **事实进 memory,过程进 skill,不混** |

**一句话:L2 的本质是"给 OpenManus 装一个学习闭环" —— agent 干活 → trace 沉淀 → skill/memory 进化 → 下次更好。** 这一层 opencode 完全没有,是 OpenManus 的核心竞争力来源。

### L3 · Loop 工程 — 对标 multica + 业界 loop engineering

L3 这个领域**没有统治性标准**,业界分成几类:

| 对标 | 思路 | 与 OpenManus 的关系 |
|---|---|---|
| [ multica-ai ](https://github.com/multica-ai/multica) | managed agents platform,agent 当 teammate,skill 复合 | 最接近 OpenManus 的 L3 设想,但偏团队管理,loop 编排较弱 |
| MetaGPT | 编码 SOP 流水线(PM/架构/编码/测试 角色串行) | 预定义流水线,不是可编排 loop 模板 |
| AutoGen / CrewAI | 对话/角色驱动多 agent | 通用框架,工程深度不足 |
| [ LangChain: The Art of Loop Engineering ](https://www.langchain.com/blog/the-art-of-loop-engineering) | loop 是可调试/评估/部署的工程对象 | **理念对标** |
| [ Claude Code loop engineering ](https://www.kunalganglani.com/blog/loop-engineering-agent-loops) | 持久化指令 + skills + subagents + hooks 让 agent 自主迭代 | **最贴近 OpenManus 的"agent + 中间件 + loop 模板"思路** |

**判断:L3 赛道无标准答案 = 机会,但也意味着不能照搬,要自己定义"loop 模板"的抽象。** 具体形式(声明式 YAML / `/loop` 命令人工编排 / 两者结合)**留到 L3 启动时再定**,本文档不提前锁定。

---

## 3. 当前阶段:L1 详细方案

### 3.1 L1 原则

1. **底座对标 opencode** — 补齐"任何 coding agent 都该有的"能力,不让 L2/L3 卡在底座缺失上。
2. **保留差异化** — server 化 / 多 agent / skills / mailbox 不弱化,这些是 L2/L3 的地基。
3. **为 L2/L3 预留接口** — memory 分层、skill 进化元数据、trace 采集在 L1 就定好数据模型。
4. **不碰 loop** — L1 不引入 loop 语义,Manus 保持纯路由,TeamLeader 维持泛化协调。Loop 编排是 L3 的决策。

### 3.2 核心 Agent(L1 范围内)

| Agent | 职责 | 工具 | L1 动作 |
|---|---|---|---|
| **Manus** | 入口路由:识别任务类型,派给专家 | `dispatch`(无文件工具) | prompt 保持纯路由,**不塞 loop 语义** |
| **Coder** | 编码执行:读/写/改/跑文件 | deepagents 文件工具 + `execute` | **P0: 重写 prompt**,对齐 opencode 编码质量约束 |
| **Researcher** | 只读调研:列/读/搜/grep | deepagents 只读工具 | **P0: prompt 补强**,明确"一次性调用"语境 |
| **TeamLeader** | 泛化协调:拆任务 + dispatch | `dispatch` / mailbox / whiteboard | **P0: prompt 补强**,L1 维持现状,**L3 再决定是否升级为 loop agent** |

**未来测试相关 Agent(Tester / 测试设计/执行/分析)不在 L1 范围**,留待 L3 随 loop 模板逐步引入。

### 3.3 L1 任务清单与优先级

| 优先级 | 任务 | 服务的层 | 说明 |
|---|---|---|---|
| **P0** | 重写 Coder/Researcher/TeamLeader prompt,对齐 opencode 编码质量约束 | L1 | 当前 Coder prompt 仅 3 行,严重拖低质量 |
| **P0** | 定义 L1 memory 数据模型(分层,为 L2 llmwiki 预留) | L1 + L2 接口 | working / episodic / semantic 三层,不能单一 storage |
| **P0** | skill 定义增加"进化元数据"字段 + trace 采集机制落地 | L1 + L2 接口 | version / 来源 trace / 置信度;AgentTraceMiddleware 演化为完整 trace 采集 |
| **P1** | 多 Provider 抽象 + 角色分模型(summarizer/title 用便宜模型) | L1 | 解耦 provider,为 auto-compact/title 铺路 |
| **P1** | 工具级权限审批 + 前端 permission dialog | L1 | 替代当前硬规则 ToolGuardMiddleware |
| **P1** | MCP Client(stdio + sse) | L1 | 工具自动注入 + 走权限审批 |
| **P2** | LSP diagnostics 工具(先 python/ts 单语言) | L1 | 让模型看到编译/类型错误自我修正 |
| **P2** | 文件版本历史(edit/write 前快照 + undo/rollback) | L1 | 与现有 watchdog SSE 天然契合 |
| **P2** | Auto-compact(summarizer 隐藏 agent + engine token 阈值触发) | L1 | 解决长对话崩溃 |
| **P2** | title 隐藏 agent(异步便宜模型生成会话标题) | L1 | 会话列表体验 |
| **P2** | AGENTS.md / memory 注入机制(类似 opencode contextPaths) | L1 | 依赖 P0 的 memory 数据模型 |
| **P3** | 通用 markdown slash 命令系统(`.md` + `$PARAM`) | L1 | 命令复用,社区可分享 |
| **P3** | agent.yaml schema 标准化 + 文档化(显式契约) | L1 + L2/L3 接口 | 输入输出契约、中间件挂点、可被 loop 引用的元数据 |

### 3.4 L1 明确不做(避免 scope creep)

- **不做 TUI** — OpenManus 是 Web/Electron 应用,不追 opencode 的 Bubble Tea 体验。
- **不做 Copilot token 自动读取** — opencode 的特化路径,非通用底座。
- **不做 Sourcegraph 内置工具** — 用 MCP 接外部即可。
- **不引入 loop 语义** — L3 的范畴,L1 阶段 Manus/TeamLeader 不改职责。

### 3.5 L1 里程碑

| 里程碑 | 内容 | 出口标准 |
|---|---|---|
| **M1 · 编码质量基线** | P0 三项(prompt 重写 + memory 数据模型 + skill/trace) | Coder 在真实编码任务上质量肉眼可见提升;memory/skill 数据模型文档定稿 |
| **M2 · 底座补齐** | P1 三项(多 provider + 权限 + MCP) | 能接外部 MCP server;工具调用有审批环;summarizer/title 用便宜模型 |
| **M3 · L1 收口** | P2 四项 + P3 两项 | L1 功能对齐 opencode,差异化优势巩固;**L1 冻结,进入 L2** |

---

## 4. L2 方案概要(L1 收口后启动)

> 本节只给骨架,细节待 L2 启动时展开。

### 4.1 目标

给 OpenManus 装上**学习闭环**:agent 干活 → trace 沉淀 → skill/memory 进化 → 下次更好。

### 4.2 核心组件

| 组件 | 职责 | 依赖 L1 |
|---|---|---|
| **llmwiki(semantic memory)** | 结构化知识库,存储代码库理解、最佳实践、踩坑记录 | L1 memory 数据模型 |
| **book2skill** | 从文档/资料自动生成 skill | L1 skill 定义 + 进化元数据 |
| **ctx2skill** | 从 agent 执行 trace 自动进化 skill | L1 trace 采集机制 |
| **三层 memory 运行时** | working(当前任务) / episodic(历史经验) / semantic(llmwiki) 的注入与衰减 | L1 memory 数据模型 |
| **进化引擎** | 借鉴 DSPy/GEPA,纯 API 调用优化 skill/prompt | L1 trace + skill |

### 4.3 L2 启动前提(L1 必须先交付)

- ✅ memory 分层数据模型(否则 llmwiki 接不上)
- ✅ skill 进化元数据字段(否则 ctx2skill 写不进)
- ✅ 结构化 trace 采集(否则进化引擎无输入)
- ✅ agent.yaml 显式契约(否则 skill 无法稳定引用 agent)

### 4.4 L2 原则(承自 Hermes)

- **memory 存事实,skill 存过程,不混。**
- **进化输入是 trace,不是人写。**
- **不造优化器,借鉴 DSPy/GEPA。**

---

## 5. L3 方案概要(L2 基础上启动)

> 本节只给骨架,细节待 L3 启动时展开。

### 5.1 目标

基于 L1 的 agent + 中间件,L2 的 skill 复合,构建**可复用的 loop 模板/脚手架**,支撑:

- **代码开发 loop**:设计 → 编码 → 测试 → 审查 → 修复 → …
- **黑盒测试 loop**:测试设计 → 测试执行 → 测试分析 → …
- **用户自定义 loop**:未来开放给用户/社区定义。

### 5.2 核心组件

| 组件 | 职责 | 依赖 |
|---|---|---|
| **loop 模板抽象** | 定义"哪一步用哪个 agent、什么中间件、满足什么条件进下一步" | **形式待定**(声明式 YAML / `/loop` 命令 / 两者结合) |
| **测试相关 Agent** | 测试设计 / 测试执行 / 测试分析 / Debugger / Reviewer 等 | L1 开放 agent 定义 |
| **loop 中间件** | 状态机 / 条件分支 / 重试 / 人工卡点 / 打断续接 | L1 中间件可插拔化 |
| **loop 模板库** | 可加载/分享的 loop 模板 | 声明式抽象(若选此形式) |

### 5.3 loop 编排入口(开放问题)

L1 明确:Loop 编排入口**不绑定 Manus**。三个候选,留到 L3 启动时决策:

1. **升级 TeamLeader** 为 loop orchestrator(复用现有 mailbox/whiteboard)
2. **新建专门 loop agent**(如 Conductor/Pipeline)
3. **`/loop` 命令人工编排**(用户在对话里手动驱动)

### 5.4 L3 启动前提(L1/L2 必须先交付)

- ✅ 开放 agent 定义(L1)
- ✅ 中间件可插拔化(L1 P3 → 提前到 L3 前)
- ✅ skill 复合可用(L2)
- ✅ 跨 session memory(L2 三层 memory)

---

## 6. 演进路线(时间线)

```
现在 ────────── L1 (基础编码平台) ────────────────► L1 收口
  │  M1 编码质量基线   M2 底座补齐   M3 L1 收口
  │  (P0 三项)         (P1 三项)     (P2+P3)
  │
  │                                                  ▼
  │                                       L2 (知识 + 进化)
  │                                       llmwiki / book2skill / ctx2skill
  │                                       三层 memory 运行时
  │                                       进化引擎(DSPy/GEPA)
  │                                                  ▼
  │                                       L3 (Loop Engine)
  │                                       loop 模板抽象
  │                                       测试 Agent + loop 库
  │                                       loop 编排入口(三选一)
  ▼
未来
```

**节奏原则:**

1. **不跳层** — L2 必须在 L1 收口后启动,L3 必须在 L2 基础上启动。
2. **每层有明确出口标准** — L1 = M3(对齐 opencode + 差异化巩固);L2/L3 待定。
3. **接口优先** — L1 阶段就要为 L2(memory 分层 / skill 进化元数据 / trace)预留接口,避免 L2 返工。
4. **不提前优化 L3** — loop 形式、测试 Agent 具体 list,留到对应阶段再定,本文档不提前锁定。

---

## 7. 当下行动项(L1 · M1)

立即开始的第一批工作,**P0 三项**:

1. **重写 Coder/Researcher/TeamLeader 的 prompt**
   - 对齐 opencode coder prompt 的编码质量约束(tone/verbosity/conventions/doing tasks/code style/proactiveness)
   - 适配 OpenManus 多 agent 语境(把"用 Agent tool 省 context"改成"dispatch 给 Researcher"等)
   - 明确每个 agent 的输入/输出/职责边界,为未来被 loop 引用做准备

2. **定义 L1 memory 数据模型**
   - 三层结构:working(当前任务) / episodic(历史经验) / semantic(llmwiki)
   - 注入机制(类似 opencode contextPaths,但分层)
   - 为 L2 llmwiki 预留接入点

3. **skill 进化元数据 + trace 采集**
   - skill 定义增加:version / 来源 trace_id / 置信度 / 进化历史
   - AgentTraceMiddleware 演化为完整 trace 采集(不只是 trace,要结构化记录 tool call / 输入输出 / 耗时 / 结果)
   - trace 存储格式定义,为 L2 ctx2skill 铺路

**下一步建议:** 先从第 1 项(Coder prompt 重写)切入,见效最快,且能顺便沉淀 OpenManus 的 agent prompt 规范。

---

## 附录 A · 业界对标速查

| 层 | 对标对象 | 链接 |
|---|---|---|
| L1 基础 | opencode(归档快照) | 本地 `D:\opencode` |
| L2 知识 | Nous Hermes Agent | https://hermes-agent.nousresearch.com/docs/ |
| L2 进化 | Hermes Self-Evolution(DSPy+GEPA) | https://github.com/NousResearch/hermes-agent-self-evolution |
| L3 loop | multica-ai | https://github.com/multica-ai/multica |
| L3 理念 | LangChain Loop Engineering | https://www.langchain.com/blog/the-art-of-loop-engineering |
| L3 理念 | Claude Code loop engineering | https://www.kunalganglani.com/blog/loop-engineering-agent-loops |

## 附录 B · 与 opencode 的能力差异全景

详见对话记录。本节仅做摘要,后续如需独立文档可拆出。

**OpenManus 领先(opencode 没有):**
- 可配置多 Agent(文件式,热更新)
- Agent 间协作(Mailbox + Whiteboard + 群聊视图)
- Skills(SKILL.md 文件包 + 只读挂载)
- Server 化 / 可嵌入(FastAPI + SSE 协议)
- Sandbox 文件浏览器(类 IDE 体验)

**OpenManus 落后(L1 阶段补齐):**
- 多 Provider + 角色分模型
- 工具级权限审批
- MCP Client
- LSP diagnostics
- 文件版本历史
- Auto-compact / summarizer / title
- AGENTS.md / memory
- 通用 markdown slash 命令

**双方都没有(未来机会):**
- Hooks(待评估,L3 中间件可能覆盖)
- 插件系统(L3 loop 模板库可能覆盖)
