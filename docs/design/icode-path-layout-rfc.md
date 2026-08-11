# RFC: iCode four-layer path layout

> **Status**: Accepted for early iteration (no backward compatibility)  
> **Date**: 2026-08-07  
> **Scope**: OpenJiuWen iCode CLI / TUI / harness path roots

## Summary

Replace the conflated `~/.openjiuwen` + `workspace` + `workdirs` model with four explicit layers:

| Layer | Name | Default path | Writable by agent? |
|-------|------|--------------|--------------------|
| 1 | **Agents home** (global) | `~/.agents/` | No (read-only by default) |
| 2 | **iCode home** (machine) | `~/.icode/` | No (read-only by default; UI/install writes) |
| 3 | **iCode project** | user-created / `-p` | Yes (project-owned state) |
| 4 | **iCode session** | `<project>/sessions/<id>/` | Yes (short-lived) |

External code repositories, docs trees, etc. are **outside** these layers. iCode may access them only when listed in the project's **`directories.json`**.

**No migration** from `~/.openjiuwen/` or old `workdirs.json`. Fresh paths only.

## Motivation

- `workdir` / `workspace` / CLI `-w` mixed “code to edit” with “agent IDENTITY/memory tree”.
- Session files, settings, and project registries shared one home, so multi-setup workflows were unclear.
- We need a first-class **iCode project** = one work setup that can reference many external directories.

## Layer details

### 1. Agents home — `~/.agents/`

Cross-harness / Agents-ecosystem shared data.

Examples:

- `~/.agents/skills/` — shared skills (already discovered by SkillUseRail)

iCode **reads** this; it does not treat it as the product home.

Override: `AGENTS_HOME` (optional).

### 2. iCode home — `~/.icode/`

Machine-local product config (not an iCode project).

| Path | Purpose |
|------|---------|
| `settings.json` | provider, model, apiKey, … |
| `mcp.json` | MCP servers |
| `models/` | saved model profiles |
| `agents/` | agent profile YAML |
| `skills.json` | optional skills path overrides |
| `OPENJIUWEN.md` / product preference files | user-level prompt prefs |
| `browser_selector_cache.json` | tool caches |

Secrets (API keys) live here (or env / keychain), **not** in `~/.agents/`.

Override: `ICODE_HOME`.

### 3. iCode project — user path

Created or opened at startup (`-p` / `--project`, or `ICODE_PROJECT`).

Suggested layout:

```text
<icode-project>/
  project.json           # metadata (name, created_at, schema version)
  directories.json      # external project roots + primary
  workspace/             # agent workspace (IDENTITY, memory, todo, skills, …)
  sessions/              # session records + per-session sidecars
  .cache/                # disposable caches
```

**`directories.json`** (replaces global `workdirs.json`):

```json
{
  "primary": "/abs/path/to/repo-a",
  "dirs": [
    "/abs/path/to/repo-a",
    "/abs/path/to/docs"
  ]
}
```

Only paths in `dirs` are intended targets for analysis/edit. Tools still use runtime cwd / permissions; product policy treats this list as the allow-list of “in setup” roots.

**`workspace/`** is the former DeepAgent agent-workspace root (IDENTITY.md, memory, …). It is **not** a code directory and must **not** be overwritten when switching primary directory.

### 4. iCode session — under project

```text
<project>/sessions/<session_id>.json
<project>/sessions/<session_id>/events.jsonl
<project>/sessions/<session_id>/sub_agents.jsonl
<project>/sessions/<session_id>/export.opencode.json
```

Session is the shortest lifecycle. `/new` creates a new id under the same project.

## CLI surface

| Flag / env | Meaning |
|------------|---------|
| `-p` / `--project` / `ICODE_PROJECT` | Open or create an iCode project directory |
| (removed as “workspace = code”) | Old `-w` no longer means agent workspace = repo |

If `--project` is omitted, default project is:

`~/.icode/projects/default`

(so first-run still works without ceremony).

Seeding directories: if `directories.json` is empty, seed **primary** from `Path.cwd()` when it looks like a real project dir (or leave empty and require `/directories add`).

## Runtime mapping

| Concept | Resolves to |
|---------|-------------|
| Agents home | `~/.agents` |
| iCode home | `~/.icode` |
| Agent workspace (`CLIConfig.workspace` / `Workspace.root_path`) | `<project>/workspace` |
| Primary directory / tool cwd / project_root | `directories.json` → primary |
| Session store | `<project>/sessions` |

**Critical rule:** switching primary directory updates tool cwd / `cfg.cwd` / pending `get_cwd()`, **not** `cfg.workspace`.

## `/cwd` display (product language)

```text
Agents home: …
iCode home: …
iCode project: …
primary directory: …
tool cwd: …
agent workspace: …
directories: N registered (see /directories)
```

## Non-goals (this RFC)

- Migrating or reading `~/.openjiuwen/**`
- Keeping `workdirs.json` at home
- Sandbox / container isolation (orthogonal)
- Multi-user / shared network projects

## Rollout

1. Land helpers + RFC.
2. Point settings/MCP/profiles/skills config at `~/.icode`.
3. Introduce `IcodeProject` + bootstrap/`-p`.
4. Move SessionStore + directories registry under project.
5. Stop binding `cfg.workspace` to primary directory.
6. Update docs/tests; drop `.openjiuwen` defaults in harness CLI.

## Alternatives considered

- Keep `~/.openjiuwen` name: rejected — product is iCode; early iteration allows rename.
- Store sessions in iCode home: rejected — sessions belong to a work setup (project).
- Put IDENTITY in iCode home: rejected — identity/memory should follow the project setup.
