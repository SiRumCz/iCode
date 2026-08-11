# 23 · 中途 Inject / Interrupt / Retry

## Chrys 摘要

- Interrupt：取消当前 run。  
- Inject：插入到下次模型调用前；可 cancel 未消费注入。  
- Retry：从当前状态重试失败/中断；可带 continuation text。  
晚到 inject 不强制再开 loop。

- 路径：`orchestration/engine/run/`（coordinator、active_injection、retry）、middleware `injection.py`

## agent-core 现状

**已对齐（P1）。** SessionHost 状态机 + DeepAgent `abort` / `steer` / `follow_up`；CLI `enable_task_loop=True`。

| EventBus | Host | Backend |
|----------|------|---------|
| `UserInterrupt` | cancel turn task | `abort()` |
| `UserInject` | 活跃 turn → `steer`；否则 `UserInjectResult(consumed=False)` | `steer` |
| `UserInjectCancel` | 未消费前标记；已消费忽略 | — |
| `UserFollowUp` | 活跃 → `follow_up`；否则新 `UserMessage` | `follow_up` |
| `UserRetry` | 重放上次 user text（可覆盖） | 新 turn |

单测：`tests/cli/unit/test_event_bus.py`（inject / cancel / follow_up / retry）。

**落点：** `harness/cli/host/session_host.py` + `LocalBackend` / `DemoBackend`。提醒类临时上下文见 [15-agent-middleware](15-agent-middleware.md)（与 inject 正交）。
