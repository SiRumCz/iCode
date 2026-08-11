# 17 · Todos

## Chrys 摘要

会话级 todo 列表跟踪；工具更新；事件 `TodoListUpdated` 推前端。

- 路径：`service/todos/tracker.py`、`service/tools/builtins/todo.py`

## agent-core 现状

**复用。** `harness/tools/todo.py`、`TodoItem` schema、CLI todo 渲染已有。

## 迁移方案

1. 保持现有 todo 工具与状态。
2. Host：todo 变更 → EventBus `TodoListUpdated`（若 TUI 需要实时侧栏）。
3. ~~无需从 Chrys 移植 tracker 实现。~~
4. **已接 TUI Tasks 侧栏**：`TodoListUpdated` → `SidebarPanel.Tasks`；Messages TOC 由 `TurnStarted` 驱动。

**落点：** 现有 harness todo；事件桥 + `tui/widgets/sidebar/`。
