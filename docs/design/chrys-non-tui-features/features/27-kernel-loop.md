# 27 · Kernel Agent Loop

## Chrys 摘要

扁平 kernel：`agent.py`、`loop.py`、`client.py`、`tools.py`、`middleware.py`、`compaction.py`——模型/工具循环、流式、工具参数错误处理、与 middleware 协作。不依赖上层 orchestration 细节。

- 路径：`kernel/`（整包）

## agent-core 现状

**复用 / 增强。** 对等物是 `DeepAgent` + ReAct/task loop + foundation LLM + tool ability manager。不必移植 Chrys kernel。

## 迁移方案

1. **不 fork Chrys kernel。** 以 DeepAgent 为执行内核。
2. 从 Chrys loop 吸收的是**契约**：streaming 身份不稳定时用 anchor、工具错误前缀、stall 重试（见 24）、reminder 不进 system（见 15）。
3. 差异用 rail / Host 补丁，而不是替换内核。

**落点：** `harness/deep_agent.py` + rails；契约测试对齐。
