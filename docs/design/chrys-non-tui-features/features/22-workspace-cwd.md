# 22 · Workspace / Session cwd

## Chrys 摘要

相对路径一律经 `SessionEnvironment.cwd` / `Workspace.primary_cwd`，禁止用进程 `os.getcwd()` 做产品路径解析。

## agent-core 现状与审计（T-27）

**Canonical API：** `openjiuwen.core.sys_operation.cwd`（`init_cwd` / `get_cwd` ContextVar）。

| 区域 | 结论 |
|------|------|
| DeepAgent 初始化 | `_ensure_initialized` → `init_cwd(workspace.root_path)` |
| filesystem / bash / fs_operation | 相对路径走 `get_cwd()` |
| CLI `CLIConfig.cwd` | 启动时 `os.getcwd()` 仅作展示/提示默认值；agent 路径以 workspace ContextVar 为准 |
| `lsp_tool` | 仍有 `os.getcwd()` **兜底**（workspace / work_dir 优先）— 可接受，已记录 |

TUI `/cwd` 打印 primary workdir + CLI workspace + `get_cwd()`，便于人工核对。

**多目标项目目录（已落地）：**
- `/workdirs` 罗列；`/workdirs add|rm|use <path|#>`
- 别名：`/workdirs-add`、`/workdirs-rm`、`/workdirs-use`（不用 `/cd`）
- 持久化：`~/.openjiuwen/workdirs.json`；primary 热应用到 cfg/agent workspace，下一回合更新 tool cwd

**不做：** 整仓禁止 `os.getcwd()`（部分库/测试合理）。
