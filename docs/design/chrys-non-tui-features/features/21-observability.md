# 21 · OTEL / 可观测性

## Chrys 摘要

Foundation observability + kernel instrumentation；可选敏感数据开关；session 下 otel 目录；LLM raw HTTP 调试日志（含密钥，仅本地）。

- 路径：`foundation/observability/`、`kernel/instrumentation.py`

## agent-core 现状

**复用。** `agent_teams/observability/`、`core/session/tracer/`、extensions otel tracer 文档。

## 迁移方案

1. 沿用现有 tracer/otel；SessionHost 生命周期打 span（turn/tool/approval）。
2. 调试用 raw HTTP 日志若需要，仿 Chrys 做 **显式 env 开关 + 警告**，默认关闭。
3. 不把 Chrys otel 目录布局强行统一；以 agent-core 现有约定为准。

**落点：** 现有 observability；Host 埋点。
