# 19 · Shell 命令过滤

## Chrys 摘要

独立 `shell_command_filtering` 实现 + `shell_filter.py` 门面；与审批/安全联动，阻断危险模式。

- 路径：`service/tools/builtins/shell_filter.py`、`shell_command_filtering/`

## agent-core 现状

**复用。** `harness/tools/shell/bash/_security.py`、powershell 对应模块、permission modes、injection 检测已存在。

## 迁移方案

1. 不替换现有 shell security；做规则集对比（Chrys deny 列表 vs agent-core），缺规则则补测补规则。
2. 对外只暴露稳定门面（类似 Chrys「勿直接 import impl 包」）。
3. 与 Hooks（05）衔接：filter 失败与 hook deny 错误文案统一 `Error: ` 前缀（若做 UI）。

**落点：** 现有 shell security；规则审计即可。
