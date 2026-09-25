# 26 · Buddy（非精灵 UI）

## Chrys 摘要

Buddy：可配置的 LLM「宠物」陪伴逻辑 + 配置；**精灵渲染属 TUI**。Headless `run` 也可能接线。属产品彩蛋/情感化层，非核心 coding 能力。

- 路径：`app/features/buddy/`（含 docs）

## agent-core 现状

**新建（低优）。** 无对等物。

## 迁移方案

1. **默认不迁。** 核心迁移完成后若有产品需求再做。
2. 若做：独立 feature 包，经 EventBus 发可选 `BuddyMessage`；不得影响主 Agent 工具循环与审批。
3. 精灵/动画留在未来 TUI；backend 只保留人格 prompt + 触发策略。

**落点：** 可选 `harness/cli/features/buddy/`。优先级最低。
