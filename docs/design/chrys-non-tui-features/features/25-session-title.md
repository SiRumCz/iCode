# 25 · Session Title（自动标题）

## Chrys 摘要

用 LLM 为会话生成短标题（backend feature）；非纯 TUI。便于 session 列表展示。

- 路径：`app/features/session_title/`

## agent-core 现状

**已落地（T-44）。**

- `SessionStore`：`title` / `updated_at` / `title_source`
- 首条 user → provisional 截断标题 + `SessionTitleUpdated`
- 首轮 `TurnFinished` 后异步 LLM refine（同 provider；失败静默；`OPENJIUWEN_SESSION_TITLE_LLM=0` 可关）
- `/sessions` 按更新时间倒序，展示标题；`*` 标记当前
- `/title [text]` 查看或手动设置（manual 锁定，LLM 不再覆盖）
- TUI 窗口标题：`产品 · 会话标题 [session_id]`

## 迁移方案

1. ~~Turn 结束后异步调用小模型~~ → `refine_title_with_llm`（`Model.invoke`）
2. ~~写入 session metadata；发 `SessionTitleUpdated`~~
3. ~~失败静默保留截断标题；不阻塞主 turn~~
4. `agent_teams.tiny_agent` 路径保留为可选后续；当前 CLI 不依赖 teams

**落点：** `harness/cli/features/session_title.py` + SessionHost 钩子。
