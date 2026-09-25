# 10 · Session 持久化 / 恢复 / Fork

## Chrys 摘要

`sessions/<id>/session.json` + `.bak` + **`session.recovery.json` 崩溃旁路**；文件锁；fork/copy；恢复须观察到 `SessionRestored` 事件才算成功。History 经 `SessionHistoryManager` 单点变更。

- 路径：`service/session/`、`service/state/store.py`

## agent-core 现状

**增强。** CLI `session_store`（`~/.openjiuwen/sessions/`）+ core checkpointer / session VCS fork。缺 Chrys 级 recovery sidecar、事务式 restore、与 EventBus 绑定的恢复契约。

## 迁移方案

1. 加固 CLI store：原子写、`.bak`、可选 `recovery.json`（写失败/崩溃时保留）。
2. SessionHost：`SessionRestore` → 加载 → `publish(SessionRestored)`；失败则清理半成品再 fallback 新会话。
3. Fork：可复用 `core/session/vcs` 或文件级 copy session 目录。
4. 与 checkpointer 二选一或分层：交互产品用 JSON 目录；长任务/team 继续用现有 checkpointer。

**落点：** `harness/cli/storage/` 演进 + Host 生命周期事件。
