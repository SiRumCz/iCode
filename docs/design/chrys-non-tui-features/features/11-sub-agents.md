# 11 · 进程内 Sub-agents

## Chrys 摘要

主 profile 声明可 spawn 的子 Agent（Explore/Plan/General 等），并发上限（如 `max_total_concurrency:2`）。工具面 `SubAgentTools`；进度事件丰富（start/progress/tool/pause/abort）。

- 路径：`orchestration/sub_agents/controller.py`、`tools.py`

## agent-core 现状（已对齐 MVP+）

**复用 / 增强。** `harness/subagents/` + `SessionRail`（`sessions_spawn` / `sessions_list` / `sessions_cancel`）+ `task_tool`。

CLI 默认子 Agent 组合（对齐 Chrys Code profile）：

- `general-purpose`（`add_general_purpose_agent=True`）
- `explore_agent` / `plan_agent`（只读 SysOperationRail）
- 可选 `browser_agent`；`research_agent` 通过 `OPENJIUWEN_CLI_RESEARCH_SUBAGENT=1`

并发：`SubagentConcurrencyLimiter`（默认 total=2、per-type=2，env `OPENJIUWEN_SUBAGENT_MAX_*` 或 `settings.json` → `subagents.max_total` / `max_per_type` / `per_agent`）。

生命周期（第二轮）：`task_tool` / `sessions_spawn` / `SessionSpawnExecutor` 写入 `subagent.started` / `subagent.finished` chunk（含 `invocation_id`、`transport` sync|async），并追加审计 `~/.openjiuwen/sessions/<parent>/sub_agents.jsonl`。EventBus 映射 `SubAgentFailed`；TUI 展示 invocation/transport。

第三轮：`SubagentParentFanInRail` 将子 Agent 内工具调用 fan-in 为 `subagent.tool_call` / `subagent.tool_result` → `SubAgentToolCallStart/Result`；`/subagents` 列出后台任务与审计尾部。

第四轮：`subagent.awaiting` / `subagent.idle` + `SubAgentsAwaiting`/`SubAgentsIdle`；会话 marker `awaiting_subagents.json`；回合结束刷新；TUI 状态栏「等待 N 个后台子 Agent」；`/subagents cancel <task_id>`；`settings.json` → `subagents.roster` 过滤默认 roster。

第五轮：`~/.openjiuwen/agents/*.yaml` 的 `sub_agents`（Chrys `Code.yaml` 形状）经 `settings.agent_profile` 合并 roster/并发；`UserSubAgentAbort`/`UserSubAgentRetry` + `/subagents abort|retry`；`SubAgentPaused`/`SubAgentAborted`/`SubAgentResumed` 事件面。

第六轮：TUI `SubAgentCard`（按 `invocation_id`）在 paused/failed(async) 时展示 **Retry / Abort**，经 EventBus 触发与 slash 相同的控制路径。

第七轮：`SubAgentCard` 内嵌 Chrys 风格 inner tool feed（`●`/`⎿`，最多 7 行）；`SubAgentToolCallStart/Result` 写入对应卡片而非独立系统行。

第八轮：`SubAgentRetryAttempt` + `subagent.retry_attempt` chunk；`task_tool` / `SessionSpawnExecutor` 对瞬时失败自动退避重试（默认 2 次，`OPENJIUWEN_SUBAGENT_MAX_RETRIES` / `settings.subagents.max_retries`）；卡片橙色 `↻ Retrying in Ns (a/b): …` 横幅。

## 迁移方案

1. 继续用 SessionRail / subagent 工厂作为实现。
2. Host 把子 Agent stream fan-in 映射为 `SubAgent*` EventBus 事件（供 TUI 工具卡）。
3. Profile 化后：把 Chrys 的 sub_agent 列表与 concurrency 写进 AgentProfile。
4. 与 **agent_teams** 区分：单用户编程会话用 subagent；多角色持久协作用 TeamAgent（见 EventBus 设计文档第 7 节）。

**落点：** 现有 harness subagents；Host 做事件桥。
