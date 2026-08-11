# Chrys 非 TUI 特性清单与迁移方案

| 项 | 值 |
|---|---|
| 日期 | 2026-07-28 |
| 范围 | Chrys 代码仓中 **TUI 以外**的产品/运行时特性 |
| 参考仓 | `/Users/michael/github/chrys`（`src/chrys/`） |
| 目标仓 | `agent-core`（`openjiuwen/`） |
| 相关设计 | [EventBus TUI 编程助手](../eventbus-tui-coding-assistant.md) |

本文目录只覆盖 **backend / orchestration / service / kernel / CLI·ACP·features**，不含 Textual 屏幕、widget、主题与 TUI 性能优化。

每个特性一份短文：`features/<slug>.md`，统一结构为：

1. **Chrys 摘要** — 做什么、关键路径  
2. **agent-core 现状** — 已有 / 部分 / 缺口  
3. **迁移方案** — 建议落点与步骤  

## 差距总览

| 级别 | 含义 | 数量（约） |
|------|------|------------|
| **复用** | 能力已齐或接近，薄适配即可 | 多 |
| **增强** | 有同类能力，需对齐 Chrys 语义/产品面 | 多 |
| **新建** | agent-core 基本无对等物 | 少（EventBus 壳、Hooks、Mutations/FS rollback、ACP、Doc converter、Buddy/Title） |

## 特性索引

| # | 特性 | 差距 | 文档 |
|---|------|------|------|
| 01 | EventBus（前后端唯一通道） | 新建 | [event-bus](features/01-event-bus.md) |
| 02 | AgentEngine / Turn / SessionHost | 增强 | [agent-engine](features/02-agent-engine.md) |
| 03 | Agent / Model Profiles（YAML） | 增强 | [profiles](features/03-profiles.md) |
| 04 | Approval 策略（含 LLM judge） | 增强 | [approval](features/04-approval.md) |
| 05 | 外部 Hooks（子进程） | 新建 | [hooks](features/05-hooks.md) |
| 06 | MCP（缓存 / 渐进披露） | 增强 | [mcp](features/06-mcp.md) |
| 07 | Skills | 复用 | [skills](features/07-skills.md) |
| 08 | 上下文 Compaction（四阶段） | 增强 | [compaction](features/08-compaction.md) |
| 09 | Mutations / 文件系统回滚 | 新建 | [mutations](features/09-mutations.md) |
| 10 | Session 持久化 / 恢复 / Fork | 增强 | [session-persistence](features/10-session-persistence.md) |
| 11 | 进程内 Sub-agents | 复用/增强 | [sub-agents](features/11-sub-agents.md) |
| 12 | ACP 外部 Sub-agents（客户端） | 新建 | [acp-sub-agents](features/12-acp-sub-agents.md) |
| 13 | ACP Server（编辑器接入） | 新建 | [acp-server](features/13-acp-server.md) |
| 14 | LLM Providers | 复用 | [llm-providers](features/14-llm-providers.md) |
| 15 | Agent Middleware（reminder / inject / validate） | 增强 | [agent-middleware](features/15-agent-middleware.md) |
| 16 | Headless CLI `run` | 复用 | [headless-cli](features/16-headless-cli.md) |
| 17 | Todos | 复用 | [todos](features/17-todos.md) |
| 18 | 内置工具面（fs / shell / search / ask_user / sleep / doc） | 增强 | [builtin-tools](features/18-builtin-tools.md) |
| 19 | Shell 命令过滤 | 复用 | [shell-filter](features/19-shell-filter.md) |
| 20 | Vision / 多模态图片 | 复用 | [vision](features/20-vision.md) |
| 21 | OTEL / 可观测性 | 复用 | [observability](features/21-observability.md) |
| 22 | Workspace / SessionEnvironment cwd | 增强 | [workspace-cwd](features/22-workspace-cwd.md) |
| 23 | 中途 Inject / Interrupt / Retry | 增强 | [inject-interrupt-retry](features/23-inject-interrupt-retry.md) |
| 24 | Stream stall 重试 | 增强 | [stream-stall-retry](features/24-stream-stall-retry.md) |
| 25 | Session Title（自动标题） | 已落地 | [session-title](features/25-session-title.md) |
| 26 | Buddy（配置 + LLM 宠物，非精灵 UI） | 新建（低优） | [buddy](features/26-buddy.md) |
| 27 | Kernel Agent Loop | 复用/增强 | [kernel-loop](features/27-kernel-loop.md) |
| 28 | Bootstrap / Settings / Installer | 增强 | [bootstrap-settings](features/28-bootstrap-settings.md) |

## 建议迁移顺序

```
P0 ✅  01 EventBus + 02 SessionHost + 16 Headless/`run` + 默认 `tui`/`chat`
P1 ✅  04 Approval · 15/23 Inject·FollowUp·reminder 契约 · TUI 人机
P2 ✅ MVP  03/20 models slash · 10/21–22 session · 08/25 compaction 事件 · 11/26 subagent 可见 · 28 bootstrap · 22 cwd 审计
P3  13 ACP Server · 12 ACP Sub-agents · Team fan-in
P4  09 Mutations · 05 Hooks · 18 Doc converter · 25 Title · 24 Stall · 26 Buddy
```

已较强、优先「接壳不重写」：07 Skills、14 LLM、17 Todos、19 Shell filter、20 Vision、21 OTEL。

## 刻意不收录（TUI-only）

- Textual screens / widgets / chrome / markdown 渲染器  
- 大历史 batch mount、Footer/CSS 局部性、GC-freeze UI 契约  
- Diff pane 的纯展示层（**Mutations 后端**在本目录；diff **视图**不算）  
- Theme / buddy sprites  

## 与 EventBus 设计文档的关系

前后端通道、TUI 接法、以及「与其他 agent-core Agent 协作不经 UI Bus」见  
[`../eventbus-tui-coding-assistant.md`](../eventbus-tui-coding-assistant.md)。  
本目录按 **能力域**拆分迁移任务，避免把所有东西塞进一篇。
