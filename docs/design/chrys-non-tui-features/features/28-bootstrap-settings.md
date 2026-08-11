# 28 · Bootstrap / Settings / Installer

## Chrys 摘要

统一 `bootstrap_runtime`：加载 .env、清理 proxy、foundation patches、`Settings.from_env()`、otel。配置目录 `~/.chrys`（Win `%APPDATA%`）。`chrys install` 安装器；跨平台经 `foundation.platform`。

- 路径：`orchestration/startup.py`、`foundation/config/`、`foundation/platform/`、`app/installer.py`

## agent-core 现状

**增强。** CLI 有 settings.json、安装脚本（`install.sh`/`ps1`）、env 覆盖。启动路径分散，不如 Chrys 单入口严格。

## 迁移方案

1. 收敛 SessionHost/CLI/ACP 入口：共用 `bootstrap_cli_runtime()`（读 settings、日志、Runner.start）。
2. 配置目录保持 `~/.openjiuwen`；文档化与 Chrys `~/.chrys` 的字段映射（迁移用户配置时用）。
3. Platform 分支继续走现有代码；新增能力时避免裸 `sys.platform`。
4. Installer 维持现有一键脚本即可。

**落点：** `harness/cli/` startup 模块。随 P0 Host 一起做。
