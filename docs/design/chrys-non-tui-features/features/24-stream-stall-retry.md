# 24 · Stream stall 重试

## Chrys 摘要

Executor 在流式输出上做 stall 检测，最多 `_MAX_RETRIES=5` 的 stream-stall 重试循环，避免挂死中的半截流。

- 路径：`orchestration/engine/executor.py`（及 `run/stream_stall` 相关测试）

## agent-core 现状

**增强。** LLM 层有 `stream_idle_timeout`；无 Executor 级 stall-retry 环。

## 迁移方案

1. 在 SessionHost 或 DeepAgent 流式消费处增加 idle 看门狗：超时 → cancel 当前流 → 有限次重试（不清用户 turn，或按 Chrys 语义重放）。
2. 与 provider 自带 timeout 协调，避免双重取消竞态。
3. 发 `RetryAttempt` 事件给 UI/日志。
4. 优先级低于控制面；属稳定性增强。

**落点：** Host 或 `harness` 流式包装器；可选下沉到 foundation LLM。
