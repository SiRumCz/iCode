# 06 · MCP

## Chrys 摘要

Profile 声明 `tools.mcp`（stdio | http）。连接缓存、owned lifecycle、HTTP 头 `{{ENV_VAR}}` 模板。`use_progressive_disclosure`：按 server list/load/unload；`always_load` 为初始可见子集。

- 路径：`service/mcp/`（`adapter.py`、`cache.py`、`owned.py`）

## agent-core 现状

**增强。** 有 stdio / streamable-http / SSE 客户端与 `progressive_tool_rail`；CLI 可读 `~/.openjiuwen/mcp.json`。缺 Chrys 级 MCP 连接缓存与「按 server 渐进披露」产品面。

## 迁移方案

1. 复用现有 MCP client；把配置统一进 profile / settings（兼容现有 mcp.json）。
2. 增强：进程内 `MCPConnectionCache`（按 cwd+config hash），避免每次 turn 重连。
3. 渐进披露：扩展 `ProgressiveToolRail` 或 MCP rail，暴露 list/load/unload 工具；`always_load` 映射初始可见集。
4. EventBus：MCP 加载进度可发 `AgentLoadProgress` 类事件（可选）。

**落点：** `core/foundation/tool/mcp/` + `harness/rails/mcp_rail.py`。
