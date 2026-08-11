# 02 · AgentEngine / TurnCoordinator / SessionHost

## Chrys 摘要

长生命周期后端：`AgentEngine` 管 session、订阅、profile/workspace 切换、rollback、MCP cache、≤1 Executor。`TurnCoordinator` 管 user message / interrupt / retry / inject。`Executor` 只跑单次 `agent.run()` + stream-stall 重试。`ChrysSessionHost` 给 headless CLI / ACP 包一层 Bus+Engine。

- 路径：`orchestration/engine/`、`orchestration/session_host.py`

## agent-core 现状

**增强。** 有 `DeepAgent`、`task_loop`、`steer`/`follow_up`/`abort`，以及 CLI `LocalBackend`，但无 Chrys 式长驻 Engine + Turn 状态机 + 统一 SessionHost。

## 迁移方案

1. 新建 `SessionHost`：持 EventBus + DeepAgent（或 `LocalBackend`）+ `session_id`；订阅 `User*`。
2. Turn 语义先用「一次 `run_agent_streaming` = 一 turn」；中途控制走 `abort`/`steer`/`InteractiveInput`。
3. 后续再抽 `TurnCoordinator`（gating、retry、finalize）与轻量 FSM，不必一次移植 Chrys 全量 Protocol 矩阵。
4. Headless / REPL /（未来）ACP 共用同一 Host。

**落点：** `harness/cli/host/` 或 `harness/runtime/`。优先薄壳，避免复制 Chrys Engine 全部文件。
