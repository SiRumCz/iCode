# 04 · Approval 策略

## Chrys 摘要

`ApprovalLevel`（AUTO/REQUIRE/SKIP）与 `ApprovalMode`（MANUAL / AUTO=LLM judge / BYPASS）。三级解析：session 覆盖 → profile 工具覆盖 → profile 默认。按 **tool kind**（含点号最长前缀）匹配。Judge 可自动批危险操作。

- 路径：`service/approval/`（`policy.py`、`judge.py`、`arbitration.py`）

## agent-core 现状

**增强。** 有 `PermissionEngine`、`ConfirmInterruptRail`、tiered policy，以及 team 侧审批。缺 Chrys 的 **AUTO LLM judge** 模式与 kind 前缀覆盖模型。

## 迁移方案

1. 保留现有 interrupt + permission 作为 MANUAL 路径；经 EventBus 暴露 `ApprovalRequest` / `UserApproval`。
2. 增加 session/profile 级 `ApprovalMode` 配置，对齐 BYPASS（headless）与 MANUAL（交互）。
3. 可选 P2：实现 `ApprovalJudge`（小模型/廉价调用）作为 AUTO 模式；**禁止** hooks/外部进程授予审批。
4. Tool kind 可对齐 Chrys 字符串集合，或映射到现有 permission rule 的 tool name/pattern。

**落点：** `harness/security/` + `harness/rails/interrupt/`；Host 负责 UI 往返。
