# 18 · 内置工具面

## Chrys 摘要

工具 kind：shell、filesystem.read/write、search、ask_user、sleep、sub_agent、mcp、**doc_converter**。Kind 存在 `tool.chrys_kind` 旁路字段。Vendored ripgrep 用于 search。

- 路径：`service/tools/builtins/`、`foundation/tool_kinds.py`

## agent-core 现状

**增强。** fs/shell/search（grep）/ask_user/sleep/subagent/mcp 基本都有。**缺 doc_converter**（办公文档转文本等）。

## 迁移方案

1. 能力矩阵对齐：列出 Chrys 每个 builtin 与 harness tool 的 1:1 表，缺什么补什么。
2. **Doc converter：** 新工具（可选依赖），输入 path → 提取文本；注意沙箱与体积限制。
3. Kind 元数据：若审批/hooks 需要 kind，在 ToolCard 或旁路 attr 上挂稳定 kind 字符串，对齐 Chrys 集合。
4. Search：继续用现有 grep/rg 路径；可考虑 vendored rg 脚本（Chrys `scripts/fetch_rg.sh`）提升 Windows 体验。

**落点：** `harness/tools/`；doc_converter 为显式新特性。
