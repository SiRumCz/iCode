# 12 · ACP 外部 Sub-agents（客户端）

## Chrys 摘要

Agent profile 带 `acp:` 段 → 强制 `sub_agent_only`，经 `acp_controller` + `service/acp_client` spawn 外部 ACP 进程当子 Agent。失败策略：仅 spawn+initialize 自动重试；其后 pause `acp_transport`。审计产物落父 session，argv HMAC 脱敏。

- 路径：`orchestration/sub_agents/acp_controller.py`、`service/acp_client/`

## agent-core 现状

**新建。** agent_teams 有 Bridge / External CLI 方向，但是「文本 relay / MCP 成员」，不是完整 ACP client 子 Agent。

## 迁移方案

1. 评估优先级：若目标是接 Claude Code/Codex，可优先复用 **Bridge / External CLI**（已有），不必先做 ACP client。
2. 若需要标准 ACP 子 Agent：实现精简 `AcpClient`（stdio JSON-RPC：session/new、prompt、cancel），挂到 subagent tool。
3. Profile 字段 `acp: { command, args, env }`；权限与审计落父 session 目录。
4. EventBus：复用 SubAgent* 事件，payload 标明 `transport=acp`。

**落点：** `harness/acp_client/`（新）或扩展 `agent_teams` bridge。P3+。
