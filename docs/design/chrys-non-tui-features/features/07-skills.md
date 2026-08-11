# 07 · Skills

## Chrys 摘要

从 `~/.chrys/skills`、可选 `~/.agents/skills` / `<cwd>/.agents/skills`、以及 profile 内联加载 skills；runner 执行 skill 工作流。

- 路径：`service/skills/`
- 工具：`load_skill` / `read_skill_resource` / `run_skill_script`
- Profile：`skills.paths` / `skills.inline` / auto_load_* 开关

## agent-core 现状（已对齐）

**复用 + 补齐。**

| Chrys | OpenJiuWen iCode |
|-------|------------------|
| 路径扫描 | `collect_default_skill_dirs`：openjiuwen/claude/codex/jiuwenclaw + `~/.chrys/skills` + `~/.agents/skills` + `<cwd>/.agents/skills` |
| depth-2 发现 | `SkillUseRail` + `cli/skills/scan.py` |
| inline skills | `~/.openjiuwen/skills.json`（及 `settings.json["skills"]`）→ `SkillUseRail(inline_skills=…)` |
| `load_skill` / `read_skill_resource` | `skill_tool`（`relative_file_path`） |
| `run_skill_script` | `RunSkillScriptTool` + `SubprocessScriptRunner` |
| TUI slash | EventBus：`/<skill>` 注入 SKILL.md；`/skills` 列表；SuggestionList 动态条目 |
| 热刷新 | SkillUseRail mtime + `<cwd>` sentinel 每 turn 解析 |

## 配置

`~/.openjiuwen/skills.json` 示例：

```json
{
  "paths": ["~/my-skills"],
  "inline": [
    {
      "name": "style-note",
      "description": "Brief style reminder",
      "instructions": "Prefer concise diffs."
    }
  ],
  "script_timeout": 300,
  "auto_load_chrys_skills": true,
  "auto_load_user_agents_skills": true,
  "auto_load_cwd_agents_skills": true
}
```

也可在 `~/.openjiuwen/settings.json` 写入 `"skills": { … }` 覆盖。

## 落点

- `openjiuwen_icode/skills/`
- `openjiuwen/harness/tools/skills/{script_runner,run_skill_script}.py`
- `openjiuwen/harness/rails/skills/skill_use_rail.py`
- `openjiuwen_icode/host/commands.py`、`tui/widgets/suggestion_list.py`
