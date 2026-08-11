# 01 · EventBus

## Chrys 摘要

进程内异步 pub/sub，**frontend ↔ backend 唯一通道**。`subscribe` 内联 await（反压、不丢）；`stream` 每消费者无界 `asyncio.Queue`（不丢 token）。事件类型覆盖 User*、Tool*、Approval*、Session* 等。

- 路径：`foundation/events/bus.py`、`types.py`

## agent-core 现状

**MVP 已落地（最小子集 + Textual TUI 壳）。** 完整审批/inject 等仍待做。`agent_teams` EventBus / Pulsar MQ 仍不作 UI 总线。

> **不会**把 Chrys 源码树原样迁入：Chrys 需 Python 3.14+，agent-core 为 `>=3.11,<3.14`；执行核用 DeepAgent，壳对齐 Chrys EventBus。

## 已实现（MVP）

| 组件 | 路径 |
|------|------|
| EventBus + stream/subscribe | `openjiuwen_icode/events/bus.py` |
| 事件子集 | `events/types.py` |
| OutputSchema → Event | `events/mapping.py` |
| SessionHost（turn 后台任务） | `host/session_host.py` |
| DemoBackend | `host/demo_backend.py` |
| Headless | `openjiuwen bus-run [--demo]` |
| Textual TUI | `openjiuwen tui [--demo]`（需 `openjiuwen[tui]`） |

```bash
uv sync --extra tui
uv run openjiuwen bus-run --demo "hello"
uv run openjiuwen tui --demo
```

## 迁移方案（后续）

1. ~~EventBus + SessionHost + bus-run~~  
2. ~~Textual TUI 最小壳~~  
3. Approval / Inject；默认 `run`/`repl` 切到 Bus  
4. 富 TUI（工具卡、审批 Modal、session 列表）对齐 Chrys 产品面，仍不拷贝 Chrys widget 树  

**落点：** harness/app 壳，不进 `core`；Python 跟随 agent-core（3.11–3.13）。
