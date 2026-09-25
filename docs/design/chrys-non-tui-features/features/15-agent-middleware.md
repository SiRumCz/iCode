# 15 · Agent Middleware（reminder / inject / validate）

## Chrys 摘要

- **SystemReminder：** 每 turn 临时上下文挂在**最后一条 user** 的 `<system-reminder>`，不进 system prompt（保 KV-cache），不持久化。  
- **Injection：** 运行中注入；交易式 batch；晚到且未消费则退回输入框（不强制 reloop）。  
- **Response validation：** 校验模型输出形态。  
另有 approval / tool event middleware。

- 路径：`service/agent_middleware/`

## agent-core 现状

**已对齐（P1）。** `PromptAttachmentManager` + ContextEngine window mutator；EventBus `UserInject`/`UserFollowUp`/`UserInterrupt`/`UserRetry` 经 SessionHost → DeepAgent。

无独立 Chrys-style response-validation middleware（可选后续 rail）。

---

## T-16 契约：System reminder / Prompt attachment

本契约是 **产品规则**，实现落在 harness，不经 UI EventBus 广播正文。

### 1. 什么是 attachment / reminder

| 概念 | 含义 |
|------|------|
| **Prompt attachment** | 某次 **model call** 可见的动态片段（todo、memory、runtime、file ref、heartbeat 等） |
| **`<system-reminder>`** | attachment 渲染外壳；告诉模型「系统自动附加、勿当作用户指令回复」 |
| **`<prompt-attachment type="…">`** | 单条 attachment 的 XML 包裹 |

静态说明段（告诉模型这些标签含义）可进 **system prompt**（`build_prompt_attachments_section`）。  
**动态内容本身不得**改写 system prompt 字符串（避免打碎 KV-cache / 污染持久 system）。

### 2. 写入与可见性

1. Rails / tools 经 `agent.prompt_attachment_manager.bind_context(ctx)` 写 section（`add_section` / `clear_section`）。  
2. `PromptAttachmentManager` **仅内存**：按 `session_id` 分桶；**不**写入 `session_store` / checkpointer / 对话 history 落盘。  
3. 每次 model call 前，ContextEngine **final-window mutator**（`make_window_mutator`）：  
   - `collect_for_session` → `render` → `inject_messages`  
4. `inject_messages`：在当前 window 消息列表 **末尾追加一条独立 `UserMessage`**，内容为整块 `<system-reminder>…</system-reminder>`。  
   - **差异（相对 Chrys）：** Chrys 常挂在「最后一条 user」正文；agent-core 用 **额外 user 消息**，不改写用户原文。  
5. 过期（`expires_at`）与 truncate（单条 / 总渲染上限）在 collect/render 时处理。

### 3. 禁止事项

| 禁止 | 原因 |
|------|------|
| 把动态 attachment 拼进 `SystemPromptBuilder` 的 identity/system 主串 | 打碎 cache、污染长期 system |
| 把 rendered reminder 当用户可见 transcript 经 EventBus 推送 | UI 噪声；属模型侧上下文 |
| 把 attachment 桶持久化进 session JSON | 违反「每 call 临时」语义 |
| Rails 直接 `bus.publish` reminder 正文 | Host 才是 UI 边界 |

### 4. 与 EventBus / Host 的边界

| 通道 | 职责 |
|------|------|
| **PromptAttachmentManager** | 模型侧临时上下文 |
| **UserInject → `steer`** | 运行中加料（task-loop 队列；需 `enable_task_loop`） |
| **UserFollowUp → `follow_up`** | 本轮迭代后追加；无活跃 turn 时降级为新 `UserMessage` |
| **UserInjectCancel** | 仅在未 `steer` 前有效；已消费忽略 |
| **晚到 inject** | Host 发 `UserInjectResult(consumed=False)`，**不**强制新开 loop |

Approval / Ask 走 interrupt + `InteractiveInput`，与 reminder **正交**。

### 5. 谁在写 attachment（现状）

| 来源 | kind / section（典型） |
|------|------------------------|
| `ContextAssembleRail` | heartbeat 等 → attachment；workspace/identity 等仍可走 system builder |
| `AgentModeRail` | runtime / plan 动态态 |
| `CodingMemoryRail` | memory |
| Browser runtime | progress continuation |

新增 rail 时应优先 `PromptAttachmentKind` + `bind_context`，而不是改 system prompt。

### 6. 可选后续（非 P1）

- Response validation rail（空回复 / 伪称已改文件 → `follow_up` nudge）  
- 与 Chrys 完全一致的「挂最后一条 user」合并策略（若评测需要）

---

## 迁移方案（执行记录）

1. ✅ Reminder：现有 PromptAttachment / ContextAssemble；契约见上（T-16）。  
2. ✅ Inject：EventBus `UserInject` → `steer`；晚到 `UserInjectResult(consumed=False)`；`UserInjectCancel`。  
3. ✅ Follow-up / Retry：`UserFollowUp` / `UserRetry`。  
4. ⬜ Validation：可选，不阻塞 P1。  
5. ✅ 不拷贝 Chrys middleware 树。

**落点：** `harness/prompts/prompt_attachment_manager.py`、相关 rails、`harness/cli/host/session_host.py`。
