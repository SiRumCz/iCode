# 09 · Mutations / 文件系统回滚

## Chrys 摘要

跟踪写文件 / edit / 可疑 shell 对工作区的变更；`GitDiffCalibrator`、snapshot、按 turn rollback（可连同对话一起回滚）。范围 = cmd cwd ∪ workspace.primary_cwd。

- 路径：`service/mutations/`、`orchestration/engine/rollback.py`

## agent-core 现状

**新建（文件系统侧）。** Session VCS（`core/session/vcs/`）管的是对话/状态快照与 fork，**不是**工作区文件 mutation 追踪与 FS 还原。

## 迁移方案

1. 定义 `MutationTracker`：在 write/edit 工具与危险 shell 后记录 before/after 或 git diff 片段。
2. 依赖 git 时用 `git diff` / 临时 blob；无 git 时用文件快照目录（类似 Chrys `mutations/`）。
3. `UserRollback(target_turn)` → Host：裁剪 session history + 按 turn 还原文件（可选 flag）。
4. 与 permission / ConfirmInterrupt 协同：先批准再记录 mutation。
5. UI 只消费 `MutationRecorded` / rollback 结果事件；diff 视图属 TUI，本特性只保证后端数据。

**落点：** `harness/mutations/`（新）。优先级 P3，工作量大、价值高。
