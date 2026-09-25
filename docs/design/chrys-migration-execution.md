# Chrys → agent-core 迁移执行说明

| 项 | 值 |
|---|---|
| 日期 | 2026-08-03 |
| Python | agent-core：`requires-python = ">=3.11,<3.14"`（**不能**直接跑 Chrys 3.14+ 树） |

## 不会做的事

- **整仓拷贝** `chrys/src/chrys` 进 agent-core（版本、kernel、双运行时冲突）。  
- 用 Chrys kernel 替换 DeepAgent。

## 按计划在做的事

| 阶段 | 内容 | 状态 |
|------|------|------|
| P0 | EventBus + SessionHost + `bus-run` | 已有 |
| P0/P2 | Textual TUI 最小壳 `openjiuwen tui` | **本次落地** |
| P1+ | Approval / Inject / 富 TUI / ACP… | 未做 |

## 本次交付

- `harness/cli/tui/`：Textual UI，只 publish/subscribe EventBus  
- SessionHost：User turn 改为后台 task，避免卡住 UI  
- `pyproject` extra：`tui = ["openjiuwen[cli]", "textual>=1.0.0"]`  
- 命令：`openjiuwen tui [--demo]`

## 试用

```bash
uv sync --extra tui
uv run openjiuwen tui --demo          # 无 API Key
uv run openjiuwen tui                 # 需已配置 settings / API Key
```

## 未完成项与优先级

见 **[chrys-migration-todo.md](chrys-migration-todo.md)**。
