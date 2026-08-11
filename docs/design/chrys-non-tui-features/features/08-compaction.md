# 08 · 上下文 Compaction（四阶段）

## Chrys 摘要

Turn-aware 四阶段压缩；触发阈值 ≈ context window − max output − safety margin（至少 5k 或 5%）。Phase-4 `last_words` 用所属 Agent 的 ModelProfile。有 spill / budgets / scoped 策略。

- 路径：`service/context/compaction/`、`kernel/compaction.py`

## agent-core 现状

**增强。** `core/context_engine/` 有 micro/full compact、round-level compressor、DialogueCompressor（CLI `/compact`）。语义是多阶段管线，但非 Chrys 的 turn/last_words 模型。

## 迁移方案

1. 短期：继续用 ContextProcessorRail + 手动 `/compact`；保证 Host 在压缩前后发 UI 事件（`CompactionStarted/Finished`）。
2. 中期：把触发阈值对齐「窗口 − 输出 − margin」；在 turn 边界自动触发（SessionHost 或 rail）。
3. 评估移植 `last_words`：压缩前用当前 model 再要一轮收尾摘要，写入 history marker。
4. 注意 Chrys 警告：message_id/call_id 非全局唯一——迁移时沿用 agent-core 自己的 id 策略，勿照搬脆弱假设。

**落点：** `core/context_engine/` + harness context rails。
