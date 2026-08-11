# 16 · Headless CLI `run`

## Chrys 摘要

`chrys run "prompt" --agent Code`：无 TUI，经 SessionHost 跑一轮；默认 `ApprovalMode.BYPASS`，禁止 ask_user。另有 agents/models/install/serve/acp 子命令。

- 路径：`app/cli/run.py`、`profiles.py`、`serve.py`

## agent-core 现状

**对齐中。** `openjiuwen run` 经 SessionHost + EventBus；默认 BYPASS（auto-approve）。

已对齐 Chrys flags：`-a/--agent`、`-s/--session`、`-C/--workdir`、`-t/--task`、`--json`（`{session_id,result,duration}`）。另保留 `-f text|json|stream-json`。顶层 `openjiuwen agents|models [--json]` 可列 profile。

## 迁移方案

1. ~~把 runner 改为经 SessionHost + EventBus~~ ✅  
2. ~~输出格式：保留 text/json/stream-json；`--json` 对齐最终结果形~~ ✅  
3. ~~Flags：`--agent`/`--session`/`--workdir`/`--task`~~ ✅  
4. ~~Headless 默认 BYPASS~~ ✅  

**落点：** `harness/cli/`；`features/headless_run.py` + `host/bus_runner.py`。
