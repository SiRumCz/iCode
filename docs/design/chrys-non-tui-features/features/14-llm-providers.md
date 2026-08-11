# 14 · LLM Providers

## Chrys 摘要

OpenAI（chat_completions | responses）、Anthropic、DeepSeek-OpenAI 兼容；选项经 `effective_chat_options`；Responses 的 `service_session_id` 有严格生效条件，本地 history 仍权威。

- 路径：`service/llm/`、`service/profiles/models/`

## agent-core 现状

**复用。** `core/foundation/llm/model_clients/` 覆盖更广（含多厂商）。CLI settings 已接多 provider。

## 迁移方案

1. 不迁 Chrys LLM 层；继续用 agent-core model clients。
2. Profile/Model 配置字段映射到现有 `ModelRequestConfig`。
3. 若需要 Responses `store`/`service_session_id` 语义，在对应 client 文档化并与 interrupt/retry 清会话规则对齐。
4. Host 层统一处理 provider 错误 → `Error` 事件。

**落点：** 现有 foundation LLM；仅配置与错误映射。
