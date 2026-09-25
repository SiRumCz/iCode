# 05 · 外部 Hooks（子进程）

## Chrys 摘要

`HookManager` 跑**外部子进程** hooks（非 in-process）。全局 `~/.chrys/hooks/` + 项目 `.chrys/hooks/`（项目优先，可截断链）。可拦截：`before_tool_call`、`user_prompt_submit`。可 deny/改写参数，**不能**批准或绕过 approval。

- 路径：`service/hooks/`（`manager.py`、`runner.py`、`matcher.py`、`outbox.py`）

## agent-core 现状

**新建。** 仅有 in-process rails（`AgentRail`）。无出站 subprocess hook 协议。

## 迁移方案

1. 定义 hook 配置 schema（YAML/JSON）与事件载荷（tool name/args、prompt text、cwd）。
2. 实现 `HookRunner`：timeout、stdout JSON 协议、deny/rewrite；注册为 rail 或 Host 前置过滤器。
3. 搜索路径：`~/.openjiuwen/hooks/` + `<cwd>/.openjiuwen/hooks/`（或 `.agents/hooks`）。
4. 硬约束：hook 结果不得 `grant_approval`；与 permission rail 串联时 hook 在审批之前/之后的顺序写清。
5. 安全：argv/环境消毒、无 shell=True、超时杀进程。

**落点：** `harness/hooks/`（新）+ 可选 rail 包装。优先级 P3。
