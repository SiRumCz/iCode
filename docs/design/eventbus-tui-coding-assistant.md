# 基于 EventBus 的 OpenJiuWen iCode（TUI）设计分析与实现计划

| 项 | 值 |
|---|---|
| 日期 | 2026-07-28 |
| 产品名 | **OpenJiuWen iCode**（CLI 入口仍为 `openjiuwen`） |
| 参考实现 | [Chrys](https://github.com/0x7c13/chrys)（coding agent + Textual TUI） |
| 目标落点 | `openjiuwen/harness` + 新建 app 层 EventBus / SessionHost / TUI |
| 相关模块 | `harness/cli`、`harness/deep_agent`、`core/runner`、`core/session`、`agent_teams` |
| 特性迁移拆分 | [chrys-non-tui-features/](chrys-non-tui-features/README.md)（TUI 外各能力摘要 + 迁移方案） |
| 执行说明 | [chrys-migration-execution.md](chrys-migration-execution.md)（不整仓拷贝 Chrys；Python 3.11–3.13） |
| 迁移 TODO | [chrys-migration-todo.md](chrys-migration-todo.md)（未迁移项 + 优先级） |

本文记录对 Chrys 架构的结论，以及在 agent-core 上复用现有框架实现 **OpenJiuWen iCode** 编程助手的计划；并说明该助手如何与 agent-core 运行时交互，以及如何与其他同样基于 agent-core 的 Agent 协作。

**按特性拆分的清单与迁移方案**见同目录 [`chrys-non-tui-features/`](chrys-non-tui-features/README.md)（EventBus、Engine、Approval、Hooks、Mutations、ACP 等 28 项，不含纯 TUI）。

---

## 1. 背景与结论摘要

### 1.1 Chrys 给人的印象 vs 实际核心

Chrys 是「coding agent + TUI」编程助手。表面上看前后端之间有大量异步排队，容易被理解成「核心是一个消息队列」。

**更准确的说法：** Chrys 的产品级核心是进程内 **EventBus（类型化异步 pub/sub）**，它是 frontend ↔ backend 的**唯一通道**。`asyncio.Queue` 只出现在：

- EventBus 的 `stream()` 消费者侧（无界、不丢事件）
- Textual 自身的 message pump
- 少数子系统（MCP lifecycle、ACP client、shell PTY）的局部队列

这些队列是实现细节，不是架构中心。

### 1.2 与 agent-core 里「MessageQueue」的区别（易混）

| 概念 | 用途 | 是否适合做 TUI↔Agent 通道 |
|------|------|---------------------------|
| Chrys / 本文拟建的 **App EventBus** | 单进程内 UI ↔ Engine 双向控制面 + 流式展示 | **是** |
| `openjiuwen.extensions.message_queue` / Pulsar / `FakeMQ` | 分布式 Runner（drunner）任务投递 | **否** |
| `agent_teams` 的 **coordination EventBus** | 多 Agent 协作 wake-up（mailbox / task board） | 相关但目标不同；**不要复用为 TUI 总线** |
| `harness` 的 `LoopQueues`（steer / follow_up） | DeepAgent 外环控制面缓冲 | 可作为 Host 下游，不是 UI 总线 |

**结论：** 实现 Chrys 式助手时，应新建 app 层 EventBus；不要把 UI 通道接到 Pulsar/`MessageQueueBase` 上。

### 1.3 agent-core 能否做出同类助手？

**能。** 编程 Agent 能力（工具、LLM 循环、session、审批、MCP、子 Agent）已在 `harness` 中具备；`harness/cli` 已是终端编程助手雏形。缺口主要在：

1. 统一的双向 EventBus 控制面（现 CLI 是「请求 → stream → 结束」）
2. 长生命周期 SessionHost / Engine（现 `LocalBackend` 每轮 `run_streaming`）
3. 富 TUI（现为 prompt_toolkit + rich，非 Textual 级产品壳）

---

## 2. Chrys 架构要点（对照用）

### 2.1 分层

```
app（TUI / CLI / ACP）
  → orchestration（AgentEngine、TurnCoordinator、Executor）
    → service（tools、MCP、approval、session、profiles）
      → kernel（agent loop）
        → foundation（EventBus、settings、workspace）
```

### 2.2 EventBus 语义

摘自 Chrys `foundation/events/bus.py` / `AGENTS.md`：

| API | 投递语义 |
|-----|----------|
| `subscribe(type, handler)` | `publish` 时 **await 回调**；慢 handler 反压发布者；**不丢** |
| `stream(*types)` | 每消费者一个 **无界 `asyncio.Queue`**；publish 只 enqueue；**不丢**（慢消费涨内存） |

设计意图：

- 工具卡路由依赖 subscribe 的严格顺序（`ToolCallStart` 处理完再执行工具，结果不会越过 start）
- headless/ACP 流式 token 绝不能因背压被丢弃

### 2.3 典型事件面

- **前端 → 后端：** `UserMessage`、`UserInterrupt`、`UserInject`、`UserRetry`、`UserRollback`、审批决策等
- **后端 → 前端：** `AgentMessage`、`AgentThinking`、`ToolCallStart/Result`、`ApprovalRequest`、`QuestionToUser`、session/compaction/usage 等

`AgentEngine` 长驻，订阅前端事件并驱动 turn；TUI 不直接调 kernel。

---

## 3. agent-core 侧现状映射

### 3.1 已有、可直接当「Agent 后端」的能力

| 能力 | 落点 |
|------|------|
| DeepAgent + 工具轨 | `harness/deep_agent.py`、`harness/tools/*`、`SysOperationRail` |
| 流式输出 | `Runner.run_agent_streaming` → `OutputSchema`（`core/session/stream`） |
| 工具 UI chunk | `harness/cli/rails/tool_tracker.py`（`tool_call` / `tool_result`） |
| 审批 / 提问 | `ConfirmInterruptRail`、`AskUserRail` + `InteractiveInput` |
| 中断 | `DeepAgent.abort()` |
| 中途加料 / 续跑 | `DeepAgent.steer` / `follow_up` + `LoopQueues`（需 `enable_task_loop`） |
| 会话落盘 | `harness/cli/storage/session_store.py` |
| 现有 REPL | `harness/cli/ui/repl.py` + `renderer.render_stream` |
| Backend 抽象 | `harness/cli/agent/factory.py`：`AgentBackend` / `LocalBackend` |

### 3.2 现有 CLI 交互形态（待演进）

```
用户输入
  → LocalBackend.run_streaming(query)
  → async for OutputSchema chunk → render_stream
  → pending_interactions → InteractiveInput → 再 run_streaming
```

没有统一的「publish UserMessage / stream AgentMessage」层；Ctrl+C / abort / 审批分散在 REPL 逻辑里。

### 3.3 明确不复用的组件

- `extensions/message_queue`（Pulsar）——分布式调度
- `agent_teams.agent.coordination.event_bus.EventBus`——团队 wake-up，不是 UI 总线
- 在 `openjiuwen.core` 里塞 EventBus——避免与 drunner MQ 概念撞车；EventBus 属于 **app / harness 壳**

---

## 4. 目标架构

```
┌────────────────── TUI / CLI / （可选）ACP ──────────────────┐
│  只做：bus.publish(User*)  /  bus.stream|subscribe(Agent*)   │
└────────────────────────────┬───────────────────────────────┘
                             │  App EventBus（新建）
┌────────────────────────────▼───────────────────────────────┐
│  SessionHost（新建）                                         │
│  • 订阅 User* → 调用 DeepAgent / Runner                      │
│  • 消费 OutputSchema → publish 后端事件                      │
│  • interrupt / approval future 与 InteractiveInput 桥接      │
│  • （可选）对外暴露「作为 agent-core Agent」的协作端口        │
└────────────────────────────┬───────────────────────────────┘
                             │ 现有公开 API
┌────────────────────────────▼───────────────────────────────┐
│  create_agent / DeepAgent / Rails / Session / Runner         │
│  abort · steer · follow_up · InteractiveInput                │
│  SessionRail / subagents /（可选）TeamAgent / MCP / Bridge   │
└────────────────────────────────────────────────────────────┘
```

**不变量：**

1. TUI 禁止直接调用 `Runner` / `DeepAgent`。
2. Host / Agent 禁止 import Textual / prompt_toolkit widget。
3. UI 通道只用 App EventBus；跨 Agent 协作走 agent-core 既有协作面（见第 7 节），不经 UI EventBus 穿透。

---

## 5. EventBus 设计（新建）

### 5.1 建议落点

```
openjiuwen_icode/events/          # 或独立 app 包
  __init__.py
  types.py      # Event 基类与具体事件
  bus.py        # EventBus + _EventStream
  mapping.py    # OutputSchema ↔ Event
```

单测：`tests/unit_tests/harness/cli/events/`（lossless stream、subscribe 反压、类型过滤）。

### 5.2 最小 API

```python
class EventBus:
    async def publish(self, event: Event, *, raise_handler_errors: bool = False) -> None: ...
    async def subscribe(self, event_type: type[E], handler: Callable[[E], Awaitable[None]]) -> None: ...
    async def unsubscribe(self, event_type: type[E], handler: ...) -> None: ...
    def stream(self, *event_types: type[Event]) -> AsyncIterator[Event]: ...
```

语义对齐 Chrys：`subscribe` 内联 await；`stream` 无界队列、不丢。

### 5.3 事件目录（MVP → 扩展）

**前端 → 后端**

| Event | SessionHost 动作（映射到现有 API） |
|-------|-----------------------------------|
| `UserMessage(text, session_id?)` | `Runner.run_agent_streaming(agent, {"query": text}, session=sid)` |
| `UserInterrupt` | `await agent.abort()` |
| `UserInject(text)` | `await agent.steer(text)`（需 task loop） |
| `UserFollowUp(text)` | `await agent.follow_up(text)` |
| `UserApproval(interaction_id, decision, payload)` | 完成 Host 内 future → 构造 `InteractiveInput` → 续 `run_streaming` |
| `UserAskAnswer(...)` | 同上（AskUser 路径） |

**后端 → 前端**

| Event | 来源 |
|-------|------|
| `TurnStarted` / `TurnFinished` / `Error` | Host 生命周期 |
| `AgentMessage` / `AgentThinking` | `OutputSchema` message / reasoning |
| `ToolCallStart` / `ToolCallResult` | `ToolTrackingRail` 写入的 chunk |
| `ApprovalRequest` / `QuestionToUser` | stream 中的 interaction（现 `pending_interactions`） |
| `UsageUpdate` | `TokenTrackingRail` |

映射集中在 `chunk_to_events(OutputSchema) -> list[Event]`，TUI 不直接消费 `OutputSchema`。

---

## 6. 与现有 agent-core 框架的交互

本节回答：**EventBus 助手如何「坐」在 agent-core 上，而不是另起一套 runtime。**

### 6.1 装配：只用公开工厂与 Card/Config 约定

```python
# 与现 harness/cli/agent/factory.create_agent 同路径
agent, tracker = create_agent(cfg)   # DeepAgent + rails
await Runner.start()
host = SessionHost(bus=bus, agent=agent, session_id=...)
await host.start()                   # 订阅 User*；不替代 Runner
```

遵守仓库约定：

- **Card / Config 分离：** AgentCard / ToolCard 只放身份与 schema；运行时状态在 Session / Host / rails。
- **资源经 `Runner.resource_mgr`：** 工具、MCP、子 Agent 注册保持现有路径；Host 不另建全局 registry。
- **Session 是权威对话状态：** Host 持 `session_id`，每 turn 传入 `Runner.run_agent_streaming(..., session=sid)`；落盘可继续用 `session_store` 或 core checkpointer。

### 6.2 控制面：三条现成通道，由 Host 统一翻译

| UI/产品意图 | agent-core API | 说明 |
|-------------|----------------|------|
| 新用户轮次 | `run_agent_streaming` + `{"query": str}` | 主路径 |
| 审批 / 提问恢复 | `InteractiveInput` 作为 query | 与现 REPL interrupt 循环一致 |
| 硬中断 | `agent.abort()` | 对应 `UserInterrupt` |
| 运行中纠偏 | `agent.steer(msg)` | 写入 `LoopQueues.steering`，下一次 inner invoke 前注入 |
| 轮次后追加 | `agent.follow_up(msg)` | 写入 `LoopQueues.follow_up`，外环迭代后消费 |
| 外环事件 | `DeepLoopEvent`（FOLLOWUP / STEER / ABORT） | task loop 内部；Host 一般不直接碰 queue |

**原则：** EventBus 事件是产品语言；Host 是唯一翻译器；禁止 TUI 直接调 `LoopQueues`。

### 6.3 观察面：复用 Session stream，而不是旁路 log

Agent 与 rails 已通过 `session.write_stream(OutputSchema)` 输出。Host 应：

1. 消费 `run_agent_streaming` 的 async iterator（或等价地订阅 session stream writer）
2. 映射为 EventBus 后端事件
3. **不要**再让 rails 直接 `bus.publish`（避免双写与层倒置）；若将来 rails 要发 UI 事件，经 `session.write_stream` 或 Host 注入的窄 callback，仍由 Host 进 Bus

现有 `ToolTrackingRail` / interrupt rails **可保持不动**；改的是消费端（Host 替代 `render_stream` 直读 chunk）。

### 6.4 权限与安全轨

继续挂在 DeepAgent 上：

- `SecurityRail` / permission engine
- `ConfirmInterruptRail`、`AskUserRail`
- prompt / tool security rails

EventBus 只传递「需要人确认」的请求与决策，**不实现**权限策略。策略真相仍在 harness security。

### 6.5 与 `LocalBackend` 的关系

推荐演进路径：

1. **P0：** `SessionHost` 内部仍调用与 `LocalBackend` 相同的 API（甚至组合一个 `LocalBackend`）。
2. **P1：** 将 `AgentBackend` Protocol 扩展为 `abort` / `steer` / `follow_up` / `resume_interrupt`，Host 只依赖 Protocol。
3. REPL / Textual / ACP / headless 都变成 EventBus 的不同 frontend，共享同一 Host。

### 6.6 明确边界：框架交互 vs 分布式 MQ

| 场景 | 用什么 |
|------|--------|
| 本进程 TUI ↔ 本进程 DeepAgent | **App EventBus** |
| 同进程 / 跨进程 **团队成员**协作 | **agent_teams** messager + DB + coordination（第 7 节） |
| 多机分布式 Runner 调度 | **extensions.message_queue**（与本设计无关） |

---

## 7. 与其他基于 agent-core 的 Agent 如何交互

「本助手」本身是一个挂在 EventBus 上的 **DeepAgent（或将来的 TeamAgent leader）**。与其他 agent-core Agent 交互时，**走 agent-core 的协作面，不走 UI EventBus**。UI 只看到 Host 翻译后的进度事件（工具卡、子 Agent 进度等）。

按耦合从紧到松：

### 7.1 同进程子 Agent（推荐默认）

**机制：** `harness` subagents + `SessionRail`（`sessions_spawn` / `sessions_list` / `sessions_cancel`）。

- 主 Agent（编程助手）通过工具委派 `code_agent` / `research_agent` / `explore` 等。
- 子 Agent 同为 DeepAgent 谱系，共享或隔离 workspace 由 rail / config 决定。
- UI：子 Agent 的 stream 若 fan-in 到主 session `write_stream`，Host 映射为 `SubAgent*` 类事件（可对齐 Chrys 的 sub-agent 事件）。

**适用：** 单用户编程会话内的任务拆分；实现成本最低。

### 7.2 Agent as Tool

**机制：** 将另一 `BaseAgent` 注册进主 Agent 的 AbilityManager（见 `docs/zh/2.开发指南/多智能体/AgentAsTool.md`）。

- 主 Agent 像调工具一样 `invoke` 对方。
- 适合确定性、短生命周期的专家 Agent（翻译、评审、格式化）。
- EventBus 侧：对 UI 仍表现为一次 `ToolCallStart/Result`（工具名即子 Agent）。

### 7.3 Agent Teams（多成员长协作）

**机制：** `openjiuwen.agent_teams`——`TeamAgentSpec.build()` + `Runner.run_agent_team[_streaming]`。

| 能力 | 说明 |
|------|------|
| Messager | inprocess / pyzmq；成员间点对点与广播 |
| Task board | 认领 / 完成任务 |
| Coordination EventBus | wake-up，不是 UI 总线 |
| Spawn | inprocess 或 subprocess |
| Stream | `TeamOutputSchema`（带 `source_member` / `role`）；inprocess 可 fan-out 到 leader |

**与本设计的接法：**

```
TUI ←App EventBus→ SessionHost ←→ TeamAgent(leader) ←messager/DB→ Teammate Agents
```

- SessionHost 把 `UserMessage` 转成 `Runner.interact_agent_team` / `run_agent_team_streaming`。
- 把 `TeamOutputSchema` chunk 映射为带 `source_member` 的 UI 事件。
- **不要**让 teammate 进程直接连 TUI EventBus（跨进程无共享内存）；只连 leader Host。

**适用：** 多角色持久团队（Leader + 研究员 + 实现者 + HumanAgent）。

### 7.4 外部 / 异构 Agent（仍属 agent-core 协作生态）

仓库已支持若干「远端也是（或表现得像）agent-core 成员」的路径：

| 路径 | 要点 |
|------|------|
| **Bridge Agent** | 本地完整 teammate avatar + 纯文本 relay 到外部 CLI（Claude Code / Codex 等） |
| **External CLI member + MCP** | 外部进程经团队 MCP / `OPENJIUWEN_TEAM_JOIN` 直连共享 DB + messager，成为一等成员 |
| **ExternalTeamClient** | 进程外 agent 按 scope=`member`\|`operator` 调协同工具 |

对本 TUI 助手而言：用户仍只跟 EventBus 交互；Host 若以 Team leader 运行，外部成员的进度经 leader stream → Host → UI 事件。

### 7.5 协作面选择指南

| 需求 | 选择 |
|------|------|
| 单会话内拆子任务 | Subagent + SessionRail |
| 把固定专家挂成工具 | Agent as Tool |
| 多角色、任务板、持久团队 | agent_teams |
| 接入已有外部编码 CLI | Bridge 或 External CLI + MCP |
| 仅 UI 多窗口看同一 Agent | 多 frontend 共享一个 EventBus + 同一 Host（仍单 Agent） |

### 7.6 身份与协议建议（实现时遵守）

1. **每个可协作 Agent 仍是 agent-core Agent：** 有 `AgentCard`、经 `Runner` 进入、状态进 Session。
2. **UI EventBus 的 `session_id` 与 team `team_name` / member 名分离：** 避免把 UI 会话 id 当成成员路由键。
3. **跨 Agent 消息不进 App EventBus：** 进 messager / tool result / team inbox；Host 可选地发只读 `CollaborationProgress` 给 UI。
4. **权限收窄：** team 模式下沿用 `TeamPermissionRail` / permission narrowing；单 Agent 子调用沿用父 session 策略。

---

## 8. TUI 交互方案

### 8.1 原则

- 唯一通道：EventBus。
- 工具卡挂载用 `subscribe`（顺序 + 反压）。
- Transcript / token 用 `stream`（不丢）。
- 审批用 Modal + `UserApproval` 回写。

### 8.2 审批时序

```
ConfirmInterruptRail 拦截写文件
  → session.write_stream(interaction chunk)
  → Host publish(ApprovalRequest)
  → TUI Modal
  → publish(UserApproval(allow))
  → Host 完成 future → InteractiveInput → run_streaming 续跑
  → ToolCallResult / AgentMessage …
```

### 8.3 两条前端演进路径

**A. 改造现有 CLI（P0 验证契约）**

- 输入 → `publish(UserMessage)`
- 后台 `async for ev in bus.stream(...):` 渲染
- Ctrl+C → `publish(UserInterrupt)`
- 行为对齐现 REPL，单测可回归

**B. Textual 富 TUI（P2）**

- App 持有 Bus + Host
- 主屏消费 Bus；输入框 / 审批 Dialog / 工具卡 / session 列表
- 与 Chrys 产品形态对齐，但后端仍是 agent-core

### 8.4 Frontend 种类（共享 Host）

| Frontend | 角色 |
|----------|------|
| REPL（prompt_toolkit） | 开发期 / 轻量 |
| Textual TUI | 主产品壳 |
| Headless `run` | CI / 脚本；`bus.stream` 打日志或 JSONL |
| （可选）ACP | 编辑器接入；事件子集映射到 ACP JSON-RPC |

---

## 9. 分阶段实现计划

### P0 — 骨架（契约验证）

- [x] `events/types.py` + `events/bus.py` + 单测（lossless、反压、过滤）— MVP
- [x] `mapping.py`：message / tool_call / tool_result / interaction / todo
- [x] `SessionHost`：`UserMessage` / `UserInterrupt` / `Turn*` / 审批 resume / inject
- [x] CLI 经 Bus：默认 `openjiuwen run` + `bus-run [--demo]`
- [x] Textual TUI：`openjiuwen` / `tui` / `chat` 默认经 EventBus（`--repl` 保留 legacy）
- [x] 文档：本文件与 `chrys-migration-todo.md` 同步勾选

### P1 — 人机控制面

- [x] `ApprovalRequest` / `QuestionToUser` ↔ `InteractiveInput`（headless auto / TUI 手动）
- [x] `UserInject` → `steer`；`UserFollowUp` → `follow_up`；`UserRetry`（CLI `enable_task_loop=True`）
- [x] `UsageUpdate`、基础错误事件
- [x] 扩展 `AgentBackend` Protocol（`steer` / `follow_up` / `get_usage`）
- [x] System reminder / attachment 契约文档化（T-16；见 `features/15-agent-middleware.md`）

### P2 — 富 TUI + 子 Agent 可见性

- [x] Textual 主屏 + slash（`/help` `/status` `/models` `/sessions` `/new` `/resume` `/compact` `/mcp` `/cwd` `/clear`）
- [x] SessionStore 原子写 / bak / recovery / load；Session* 事件
- [x] 工具卡底色行 + 轻量 markdown；SubAgent* / Compaction* 事件与展示
- [x] `build_host_bundle` 共用 bootstrap
- [x] （增强 MVP）角色气泡 + 可折叠 ToolCard + StatusBar + Approval/Ask Modal + slash SuggestionList
- [x] Session 标题：provisional + 可选 LLM refine + `/sessions` 列表 + `/title` + `SessionTitleUpdated`
- [x] TUI 侧栏 Messages（TOC）+ Tasks；Ctrl+G 显隐
- [x] Models Modal（F4 / bare `/models`）+ profile CRUD + LocalBackend rebuild
- [ ] （增强）完整 Chrys VirtualizedMarkdown / DiffView / Context·Debug 侧栏 / MCP cwd+hash cache / profile YAML 热重建
- [ ] （可选）headless JSONL frontend

### P3 — 团队与外部协作

- [ ] SessionHost 可选挂载 `TeamAgent` leader 路径
- [ ] `TeamOutputSchema` → 带 member 标签的 UI 事件
- [ ] Bridge / External CLI 进度只读展示
- [ ] （可选）ACP adapter

### P4 — 产品级（按需）

- [ ] rollback / profile switch / mutations（若 agent-core 无对等能力，事件可先定义、Host 返回 `Unsupported`）
- [ ] 大历史回放与性能（参考 Chrys 的 batch mount / GC 经验，按需引入）

---

## 10. 拒绝的方案（避免回潮）

| 方案 | 为何拒绝 |
|------|----------|
| 用 Pulsar / `MessageQueueBase` 做 TUI 通道 | 错误抽象；引入分布式运维成本；与 UI 低延迟需求不符 |
| 复用 `agent_teams` coordination EventBus 做 UI | wake-up 语义不同；会把 UI 耦合进团队内核 |
| TUI 直接 `async for` `OutputSchema` | 多 frontend 无法共享；难加 inject/rollback 等控制事件 |
| Rails 直接 `bus.publish` | 层倒置；rails 应依赖 session stream，由 Host 统一进 Bus |
| 每个子 Agent 进程直连 TUI Bus | 跨进程无共享 Bus；应经 leader Host fan-in |
| 在 `openjiuwen.core` 落地 App EventBus | 与 drunner MQ、session stream 职责混淆；应放 app/harness 壳 |

---

## 11. 测试策略

| 层级 | 内容 |
|------|------|
| 单测 Bus | publish/subscribe 顺序、stream 不丢、高水位日志、unsubscribe |
| 单测 mapping | 代表性 `OutputSchema` → Event |
| Host 集成 | mock agent stream；UserMessage → 事件序列；Interrupt；Approval round-trip |
| CLI 回归 | 现有 `tests/cli/` 在 Bus 改造后保持绿 |
| （P3）Team | inprocess spawn；UI 仅断言 Host 发出的 member 标签事件，不测 Textual |

---

## 12. 参考路径速查

| 主题 | 路径 |
|------|------|
| Chrys EventBus | `chrys/foundation/events/bus.py`、`types.py` |
| Chrys Engine | `chrys/orchestration/engine/engine.py`、`session_host.py` |
| 现 CLI Backend | `openjiuwen_icode/agent/factory.py` |
| 现 REPL / 渲染 | `openjiuwen_icode/ui/repl.py`、`renderer.py` |
| DeepAgent 控制 | `openjiuwen/harness/deep_agent.py`（`abort` / `steer` / `follow_up`） |
| LoopQueues | `openjiuwen/harness/task_loop/loop_queues.py` |
| OutputSchema | `openjiuwen/core/session/stream/base.py` |
| Agent as Tool | `docs/zh/2.开发指南/多智能体/AgentAsTool.md` |
| Agent Teams | `openjiuwen/agent_teams/AGENTS.md` |
| 分布式 MQ（勿作 UI） | `openjiuwen/extensions/message_queue/`、`core/runner/message_queue_base.py` |

---

## 13. 一句话路径

> 在 **harness/app 层**新建 Chrys 风格 EventBus + SessionHost；用 Host 把 UI 事件翻译成已有的 `run_agent_streaming` / `InteractiveInput` / `abort` / `steer` / `follow_up`；TUI 只绑定 Bus。与其他 agent-core Agent 的协作走 **subagent / Agent-as-Tool / agent_teams / Bridge·External**，由 Host fan-in 进度到 UI，而不是把协作流量灌进 UI EventBus。
