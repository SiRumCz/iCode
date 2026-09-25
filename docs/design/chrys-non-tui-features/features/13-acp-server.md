# 13 · ACP Server（编辑器接入）

## Chrys 摘要

`chrys acp`：把编辑器 ACP JSON-RPC 译成 SessionHost。支持 session/new|load|list|prompt|cancel|close 等；扩展方法 inject/mutations/diff/rollback/switch_agent。stdout **仅** JSON-RPC；日志走 stderr。

- 路径：`app/acp/`（`server.py`、`bridge.py`、`session_manager.py`）

## agent-core 现状

**新建。** 无 ACP server。有 headless CLI 与（team）MCP server，形态不同。

## 迁移方案

1. 依赖 P0：EventBus + SessionHost 就绪后，做薄 ACP adapter（JSON-RPC ↔ Bus 事件）。
2. Phase 1 对齐 Chrys：session CRUD + prompt + cancel；图片/资源按需。
3. 扩展能力（rollback/mutations）跟 09/10 进度挂钩，可先返回 method-not-found。
4. 入口：`openjiuwen acp` 或 `python -m ...acp`；严格 stdout 纪律。

**落点：** `harness/cli/acp/` 或 `harness/acp/server/`。P3。
