# 03 · Agent / Model Profiles（YAML）

## Chrys 摘要

内置 Agent profile：`Code` / `QA` / `Explore` / `Plan` / `General`（YAML，固定 hex id）。Code/QA 可作主 Agent；Explore/Plan/General 多为 `sub_agent_only`。Model profile 描述 provider、api_style、窗口与选项；用户目录 `~/.chrys/{agents,models}`。

- 路径：`service/profiles/agents/`、`service/profiles/models/`、`builtins/*.yaml`

## agent-core 现状

**增强（Model 侧已部分落地）。**

- Model：`/models`、`~/.openjiuwen/models/*.json`、TUI **Models Modal（F4）** CRUD；Use 写 settings 并 `LocalBackend.rebuild`
- Agent：仍有 Python 工厂型 subagents；主 Agent YAML profile 热切换尚未做

## 迁移方案

1. 短期：继续用 `create_deep_agent` / subagent 工厂；用 `harness_config.yaml` 表达工具、MCP、skills。
2. 中期：引入 `AgentProfile` 数据模型（可序列化 YAML），内置与 Chrys 对齐的角色（至少 Code + Explore/Plan）。
3. 主会话切换 profile = Host 重建 agent（或 hot-swap rails/tools），经 EventBus 发 `ProfileSwitched`。
4. ~~Model profile 映射~~ → `settings.json` + `~/.openjiuwen/models` + Modal；API key 仍走 env/settings（不对齐 Chrys 全量 headers/extra_body 表单）。

**落点：** `harness/cli/host/profiles.py`、`tui/screens/models_modal.py`；Agent YAML 仍待。
