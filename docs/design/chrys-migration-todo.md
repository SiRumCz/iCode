# Chrys → agent-core 迁移 TODO 与优先级

| 项 | 值 |
|---|---|
| 日期 | 2026-08-10 |
| 原则 | EventBus 壳 + DeepAgent 核；产品名 **OpenJiuWen iCode**；**不**整仓拷贝 Chrys（Python `>=3.11,<3.14`） |
| 已交付 | **P0–P2 MVP + 阶段 A–E 计划项 MVP**（见 [icode-chrys-migration-plan.md](icode-chrys-migration-plan.md)） |
| 特性说明 | [chrys-non-tui-features/](chrys-non-tui-features/README.md) |
| 架构设计 | [eventbus-tui-coding-assistant.md](eventbus-tui-coding-assistant.md) |
| 执行边界 | [chrys-migration-execution.md](chrys-migration-execution.md) |

本文跟踪迁移勾选。勾选请随落地更新。

---

## 优先级定义

| 级 | 含义 | 目标 |
|----|------|------|
| **P0** | 骨架收尾 | Bus 成为默认路径，行为不弱于现 CLI |
| **P1** | 人机可用 | 审批 / 提问 / 中途注入，TUI 能完成真实编码会话 |
| **P2** | 产品对齐 | 富 TUI、session、profile、MCP/压缩等常用能力 |
| **P3** | 编辑器与协作 | ACP、外部子 Agent、team 可选 |
| **P4** | 差异化 / 低优 | mutations 回滚、hooks、buddy、性能打磨 |

---

## 已完成（备忘）

- [x] P0 / P1 全项（见历史提交）
- [x] T-20 Model profiles MVP：`/models` + `~/.openjiuwen/models/*.json` + settings 切换 + **Models Modal（F4）** + LocalBackend `rebuild` 热重建
- [x] T-21 SessionStore：原子写、`.bak`、recovery sidecar、`load`/`switch`
- [x] T-22 TUI：`/sessions` `/new` `/resume` + Session* 事件
- [x] T-23 TUI：工具卡底色行 + 轻量 markdown 气泡（非完整 Chrys widget）
- [x] T-24 MCP：cwd+hash 稳定 `server_id` + `/mcp` 缓存状态 + `/mcp tools` 列表
- [x] T-25 Compaction* 事件 + `/compact`（DialogueCompressor 仍自动阈值；force API 可选后续）
- [x] T-26 SubAgent* 事件（task/`*_agent` tool 映射）+ TUI 展示
- [x] T-27 cwd 审计文档 + `/cwd`
- [x] T-28 AUTO ApprovalJudge：**明确延后**（现有 MANUAL + headless BYPASS 足够）
- [x] T-29 `build_host_bundle` 共用 bootstrap（`run`/`tui`/`acp`）
- [x] A1 `/resume` 统一：checkpoint 或 SessionStore seed DeepAgent context
- [x] A2 `/fork` 克隆 transcript + events.jsonl
- [x] A3 Session 元数据：model / workdir / agent_profile 持久化
- [x] B1 `/agents use <id>` 热切换 + rebuild
- [x] B4 Models Modal 高级项：headers / extra_body / api_key_env
- [x] T-30 ACP Server MVP：`openjiuwen acp` JSON-RPC
- [x] T-31 ACP 子 agent：`transport=acp` + AcpClient
- [x] T-40 MutationTracker + `/diff` + `/rollback`
- [x] T-41 Hooks：**发现 stub**（`/hooks`；不自动执行、不可代批）
- [x] T-43 主 turn stream stall 重试（首包 idle reopen）
- [x] E5 `/theme` `/notifications` 偏好持久化
- [x] T-44 Session 自动标题（provisional + LLM refine + `/title`）
- [x] `openjiuwen serve` 浏览器 TUI（textual-serve MVP）

---

## P0 / P1

**全部完成。**

---

## P2 — 产品对齐

**MVP 完成**（日常 TUI 可用：slash、session 列表/新建/恢复元数据、models、subagent/compaction 可见性）。

仍可增强（不阻塞标完成）：
- LocalBackend.force_compact API / Chrys 四阶段语义完全对齐
- VirtualizedMarkdown / DiffView Modal（slash `/diff` 文本已有）
- `/agents` 八 tab 全量配置 UI（`/agents use` 热切换已有）

已补：
- [x] 主 Agent profile YAML 热切换 / 重建 DeepAgent（`/agents use`）
- [x] Chrys 级 MCP connection cache（cwd+config hash → 稳定 server_id）
- [x] Models Modal 高级项（headers / extra_body / api_key_env）
- [x] TUI shell 模式：输入 `!` / `！` 切换；Esc 或再按 `!` 退出；`!cmd` 一次执行
- [x] 多 workdirs：`/workdirs` 罗列；`add`/`rm`/`use`（及 `/workdirs-add` 等别名）；primary 热切换
- [x] TUI UX 对齐 MVP：角色气泡、可折叠工具卡、StatusBar、审批/提问 Modal、slash SuggestionList、选区复制
- [x] Session 列表 + 标题：`/sessions` 展示标题（按更新时间）；首条消息 provisional；首轮后可选 LLM refine；`/title`；`SessionTitleUpdated`
- [x] TUI 侧栏 Messages（TOC）+ Tasks（todo）+ Context（用量/压缩）；Ctrl+G 显隐；点击 Messages 跳转气泡
- [x] Models 配置 TUI：F4 / bare `/models` Modal（列表+表单 CRUD）；Use 写 settings 并 `LocalBackend.rebuild`

---

## P3 — 编辑器与外部协作

| ID | 待办 | 关联特性 | 备注 |
|----|------|----------|------|
| T-30 | ✅ ACP Server MVP：`openjiuwen acp` | 13 | session new/load/list/prompt/cancel/close |
| T-31 | ✅ ACP 客户端子 Agent（`transport=acp`） | 12 | AcpClient + SubAgent* transport |
| T-32 | SessionHost 可选 TeamAgent 路径 + member 标签事件 | teams | 非 Chrys 必需（延后） |
| T-33 | Bridge / External CLI 进度只读上 Bus | — | 可选（延后） |

---

## P4 — 低优 / 差异化

| ID | 待办 | 关联特性 | 备注 |
|----|------|----------|------|
| T-40 | ✅ Mutations + `/diff` + `/rollback` | 09 | 快照目录；git 优先 |
| T-41 | ✅ Hooks 发现 stub（`/hooks`） | 05 | 不自动执行、不能代批 |
| T-42 | Doc converter 工具 | 18 | 可选依赖（延后） |
| T-43 | ✅ Stream stall 重试环 | 24 | 首包 idle reopen |
| T-44 | ✅ Session 自动标题 | 25 | provisional + LLM refine + `/title` |
| T-45 | Buddy（非精灵） | 26 | **默认不迁** |
| T-46 | 大历史 TUI 性能 | TUI | 延后 |
| T-47 | Shell filter 规则集对照补齐 | 19 | 延后 |

---

## 建议排期

```
P0✅ P1✅ P2 MVP✅ + A/B/C/D/E 计划 MVP✅
  剩余可选：T-32/33 Team/Bridge、T-42/46/47、VirtualizedMarkdown、四阶段 compaction 完全对齐
```

---

## 明确不做 / 延后

| 项 | 原因 |
|----|------|
| 整仓拷贝 Chrys `src/chrys` | Python 版本冲突 |
| 用 task loop 实现 EventBus | 职责不同 |
| P2 内 T-28 AUTO judge | 可选；MANUAL+BYPASS 已够用 |
| Chrys kernel 移植 / Buddy | 计划明确不做 |
| `chrys serve` 浏览器 TUI | ✅ `openjiuwen serve`（textual-serve；密码鉴权后续增强） |

---

## 维护方式

1. 每完成一项：勾选本文件，并更新 `eventbus-tui-coding-assistant.md` / `features/NN-*.md`。  
2. 新缺口归入 P0–P4。  
3. 范围变更先改 [chrys-migration-execution.md](chrys-migration-execution.md)。
