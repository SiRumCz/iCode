# iCode vs Chrys：子 Agent 调度架构对比

## 一、总体架构拓扑

### iCode
```
DeepAgent 外层 while 循环
  └─ LoopCoordinator（停止条件判断）
       └─ TaskLoopController（round 管理）
            └─ submit_round() → 发布 InputEvent → LLM ReAct 推理
                 └─ LLM 调用 sessions_spawn tool → 创建 SESSION_SPAWN_TASK_TYPE 任务
                      └─ TaskScheduler（后台 schedule() 循环）
                           └─ asyncio.create_task() 并发执行
                                └─ TaskExecutor（按 task_type 分发）
```

### Chrys
```
AgentEngine（EventBus 驱动）
  └─ TurnCoordinator（用户消息准入）
       └─ Executor.wrap(Agent.run())
            └─ ToolLoopLayer（ReAct 工具调用循环）
                 └─ LLM 调用 sub-agent FunctionTool
                      └─ SubAgentTools._invoke()（同步内联执行）
                           └─ SubAgentController（run→retry→pause→resolve）
```

---

## 二、核心差异逐维对比

### 1. 任务分解机制

| | iCode | Chrys |
|---|---|---|
| **分解方式** | LLM 自主调用 `sessions_spawn` tool，每次调用=一个 task | LLM 调用预先注册的 sub-agent `FunctionTool` |
| **分解时机** | 动态、LLM 推理过程中实时决定 | 动态、LLM 推理过程中实时决定 |
| **任务粒度** | 粗粒度 task（每个 task 内有完整的 ReAct 循环） | 细粒度 tool invocation（每个 sub-agent 是单次 tool call） |
| **预规划** | 无预规划，完全由 LLM 自主决策 | 无预规划，完全由 LLM 自主决策 |

**关键洞察**：两者都**不在 scheduler 层面做任务分解**。分解逻辑完全在 LLM 的推理中——LLM 看到工具描述后自主决定"这个任务需要并行调用多个子 agent"。Scheduler/Controller 只是**执行 LLM 已经做出的决策**，本身是 task-agnostic 的。

---

### 2. 调度模型

这是差异最大的维度：

| | iCode | Chrys |
|---|---|---|
| **调度器** | 独立后台 `TaskScheduler.schedule()` 循环 | 无独立调度器 |
| **调度触发** | 事件驱动（`asyncio.Event`）+ 轮询兜底 | 内联：tool call 到达即执行 |
| **任务队列** | `TaskManager` 维护 task 状态机（SUBMITTED→WORKING→COMPLETED/FAILED） | 无显式队列，`_total_active` / `_agent_active` 计数器 |
| **并发启动** | `asyncio.create_task()` 在 schedule 循环中批量启动 | 并发由父 agent 的 tool loop 自然产生：LLM 一次返回多个 function_call，每个并发执行 |
| **超限处理** | `max_concurrent_tasks` 限制，超限时跳过本轮，等待下一轮 | 立即返回错误字符串给 LLM（"retryable"），LLM 自己决定何时重试 |
| **任务生命周期** | 完整状态机：SUBMITTED/WORKING/COMPLETED/FAILED/PAUSED/CANCELED | 简单状态：`SubAgentStatus`（RUNNING/PAUSED/COMPLETED/FAILED） |

#### iCode 调度循环核心代码

```python
async def schedule(self):
    while self._running:
        # 1. 扫描所有 SUBMITTED 状态的任务
        submitted_tasks = await self._task_manager.get_task(
            task_filter=TaskFilter(status=TaskStatus.SUBMITTED))

        # 2. 并发启动新任务（受 max_concurrent_tasks 限制）
        for task in submitted_tasks:
            async with self._lock:
                if len(self._running_tasks) >= self._config.max_concurrent_tasks:
                    break
                exec_task = asyncio.create_task(
                    self._execute_task_wrapper(task.task_id, session))
                self._running_tasks[task.task_id] = (None, exec_task)

        # 3. 事件驱动等待：新任务提交时 notify_task_submitted() 唤醒
        self._submit_event.clear()
        await asyncio.wait_for(self._submit_event.wait(),
                               timeout=self._config.schedule_interval)
```

#### Chrys 并发控制核心代码

```python
async def _invoke(prompt: str) -> str:
    # 全局并发守卫
    if self._total_active >= self._max_total:
        return tool_error("sub_agent_concurrency_limit", ...)
    # 单 agent 并发守卫
    if per_active >= per_max:
        return tool_error("sub_agent_concurrency_limit", ...)
    # 通过检查后直接执行
    self._total_active += 1
    self._agent_active[tool_name] += 1
    # ... 执行 sub-agent ...
```

---

### 3. Round / Turn 管理

| | iCode | Chrys |
|---|---|---|
| **外层循环** | `TaskLoopController` 管理 round：`submit_round()` → `wait_round_completion()` → `drain_follow_up()` | `TurnCoordinator` 管理 turn：`on_user_message()` → `_admit_user_message()` → `run_fresh()` |
| **完成判定** | 所有 task 进入终端状态 → `_ensure_session_completion_signal()` 发送 `all_tasks_processed` | `TurnRunner` 执行完毕后 `TurnFinalizer` 处理 |
| **Follow-up 机制** | 有显式 `LoopQueues`，支持 `drain_follow_up()` / `enqueue_follow_up()` | 无对等机制；子 agent 结果是普通 tool result，由 LLM 在下一轮自主决定是否继续 |
| **状态机** | `LoopCoordinator` + 停止条件判断 | `EngineStateMachine`：IDLE/RUNNING/PENDING_RETRY/AWAITING_SUB_AGENTS/INTERRUPTED/FAILED |

---

### 4. 子 Agent 与父 Agent 的关系

| | iCode | Chrys |
|---|---|---|
| **耦合方式** | 通过 TaskManager 解耦：子 agent 是独立 task，通过 event queue 与父 agent 通信 | 紧耦合：子 agent 是父 agent tool loop 中的一个 tool call，`_invoke` 在父 agent 的协程上下文中执行 |
| **父 agent 等待** | `wait_round_completion()` 等待所有 task 完成 | 父 agent 的 tool loop 等待 `_invoke` 返回（tool result） |
| **上下文隔离** | 子 agent 有独立 session，独立 context | 子 agent 有独立 session（`propagate_session=False`），独立 `ContextManager` |
| **结果返回** | 通过 `TaskCompletionEvent` / `TaskInteractionEvent` 发布到 event queue | 直接作为 tool result 字符串返回，LLM 在下一轮推理中处理 |

---

### 5. Human-in-the-Loop（暂停/重试/中断）

这是 Chrys 明显更强的维度：

| | iCode | Chrys |
|---|---|---|
| **暂停语义** | `pause_task()` → 取消 asyncio.Task，状态改为 PAUSED | `SubAgentController` 有 `pending_decision` Future，暂停时等待用户 Retry/Abort 决策 |
| **重试语义** | 无显式子 agent 重试机制 | `SubAgentController.request_retry()` → 解析 `pending_decision` → 重新执行 `agent.run()` |
| **中断传播** | 取消 asyncio.Task | `cascade_abort_all()` → 遍历所有活跃 controller → 每个 controller 的 `cascade_abort()` |
| **用户交互粒度** | 会话级（整个 round） | 子 agent 级：每个子 agent 有独立的 TUI card，用户可单独 Retry/Abort |
| **持久化暂停** | 无 | 暂停状态持久化到磁盘，session 恢复时可重新加载 paused records |

#### Chrys 暂停/恢复流程

```python
async def on_sub_agent_paused(host, event):
    # 跟踪新暂停的子 agent
    first = not host._paused_sub_agents
    host._paused_sub_agents.add(event.invocation_id)
    if first:
        host._fsm.try_transition(Trigger.SUB_AGENT_PAUSED)  # → AWAITING_SUB_AGENTS
    host._history.upsert_awaiting_sub_agents_marker(...)

async def on_sub_agent_unpaused(host, event):
    # 移除子 agent，最后一个恢复时
    host._paused_sub_agents.discard(event.invocation_id)
    if not host._paused_sub_agents:
        host._fsm.try_transition(Trigger.SUB_AGENT_RESOLVED)  # → 回到 RUNNING
```

---

### 6. 重试与容错

| | iCode | Chrys |
|---|---|---|
| **重试机制** | `_execute_task_wrapper` 的 `asyncio.wait_for` + timeout → 标记 FAILED | `StreamRetryLoop`（共享于主 agent 和子 agent），支持指数退避重试 |
| **中断恢复** | 无显式持久化 | `LoopRecorder` 记录 tool loop 状态，支持中断后恢复 |
| **错误处理** | 异常捕获 → 更新 task 状态 → 发布失败事件 | `SubAgentController` 的 pause → retry → abort 完整闭环 |

---

## 三、架构选择的内在逻辑

### iCode 选择 TaskScheduler 后台调度循环的原因

1. **多 session 并发**：`TaskScheduler` 持有 `_sessions: Dict[str, Session]`，可以从多个 session 中扫描 task，天然支持多用户并发。
2. **任务类型多样性**：`TaskExecutorRegistry` 支持注册多种 task type（`DEEP_TASK_TYPE`、`SESSION_SPAWN_TASK_TYPE`），可扩展。
3. **显式生命周期管理**：完整的状态机（SUBMITTED→WORKING→COMPLETED/FAILED/PAUSED/CANCELED）让外部系统可以观察和干预 task 状态。
4. **事件驱动 + 轮询兜底**：既保证了低延迟（新任务提交时立即唤醒），又有容错能力（轮询周期兜底）。

### Chrys 选择内联 tool invocation 的原因

1. **单会话模型**：`AgentEngine` 是一个 session 一个 engine，不需要跨 session 调度。
2. **简化并发模型**：子 agent 的并发天然由 LLM 的 function_call 并发驱动，不需要额外的调度器。
3. **更丰富的 UX**：暂停/重试/中断的细粒度控制需要子 agent 与父 agent 的 tool loop 紧密耦合。
4. **事件总线架构**：`EventBus` 驱动的前端（TUI）需要实时反映每个子 agent 的状态，内联执行更容易实现事件穿透。

---

## 四、总结

**iCode 的调度是"任务队列 + 后台调度器"模式**：LLM 产生任务 → TaskManager 入队 → TaskScheduler 后台扫描并并发启动。适合多 session、多任务类型的场景。

**Chrys 的调度是"工具内联 + 状态机驱动"模式**：子 agent 是普通 FunctionTool，LLM 调用时直接在父 agent 的 tool loop 中执行，并发由 LLM 的多 function_call 自然驱动。适合单会话、需要细粒度人机交互的场景。

**两者的共同点**：分解逻辑都在 LLM 推理中，调度器/Controller 只是执行者，不做任务规划。