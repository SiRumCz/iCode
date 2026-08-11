# OpenJiuWen iCode

Terminal coding assistant (CLI / Textual TUI / ACP) built on the
[`openjiuwen`](https://gitcode.com/openJiuwen/agent-core) SDK
(DeepAgent + tools + session runtime).

Repo: [`michaelling/iCode`](https://gitcode.com/michaelling/iCode)
(PyPI / distribution name remains `openjiuwen-icode`).

This product currently depends on the
[`michaelling/agent-core`](https://gitcode.com/michaelling/agent-core) fork,
branch `icode` (not upstream `main` / PyPI alone).

## Install

```bash
# From this repo (resolves openjiuwen from the fork via [tool.uv.sources]):
cd iCode
uv sync   # requires SSH access to gitcode.com:michaelling/agent-core
```

`[tool.uv.sources]` points `openjiuwen` at
`ssh://git@gitcode.com/michaelling/agent-core.git` (`branch = "icode"`);
`uv.lock` pins the resolved commit.

### Local joint debug (SDK + product)

```bash
# 1. editable override — do not commit the path change
uv add --editable ../agent-core

# 2. develop / test against the sibling checkout, then push SDK to origin/icode

# 3. restore the git source in pyproject.toml if needed, refresh the team pin:
uv lock --upgrade-package openjiuwen
# commit uv.lock (and pyproject.toml only if sources were changed)
```

## Run

```bash
uv run icode --help
uv run icode tui
```

## Layout

| Path | Role |
|------|------|
| `openjiuwen_icode/` | Product package (EventBus, SessionHost, TUI, ACP, …) |
| `tests/cli/` | Unit / integration / e2e tests |
| `scripts/pyapp/` | Offline binary packaging |
| `docs/` | User guide + design notes |

## Relationship to agent-core

- **This repo:** product shell only.
- **Upstream SDK:** [`openJiuwen/agent-core`](https://gitcode.com/openJiuwen/agent-core)
  (`openjiuwen.core` + `openjiuwen.harness`).
- **Dev dependency:** fork
  [`michaelling/agent-core`](https://gitcode.com/michaelling/agent-core)
  on branch `icode`, declared in `[tool.uv.sources]` and pinned in `uv.lock`.
- Supported SDK import surface: `docs/design/icode-sdk-api-surface.md`.
- Compatibility: `openjiuwen.harness.cli` in agent-core is a deprecated
  shim that re-exports this package when installed.

## Tests

```bash
make test                 # unit tests
make test-report          # unit tests + HTML + coverage
make test-all             # unit + integration + e2e + HTML + coverage
make test-e2e-smoke       # no-LLM CLI/TUI smoke only
make test-e2e-llm         # real LLM e2e (needs ICODE_E2E_API_KEY)
```

`make test-all` writes:

- `reports/test-report.html` — pytest HTML (includes coverage summary + link)
- `reports/coverage/index.html` — line coverage detail

LLM e2e cases inside `test-all` **skip** (with a reminder) when `ICODE_E2E_API_KEY` is unset.

### LLM e2e credentials

Use a **dedicated** test key (do not rely on interactive `OPENLUX_TOKEN` unless you export it into the test var):

```bash
export ICODE_E2E_API_KEY=sk-...   # required for -m llm
# optional:
export ICODE_E2E_MODEL=deepseek-v4-pro          # preset id (default)
export ICODE_E2E_MODELS=all                     # or comma-separated presets
# export ICODE_E2E_API_KEY_OPENAI=...           # for openai-gpt-4o preset
```

Presets live in `tests/cli/e2e/models.yaml` (OpenLux `deepseek-v4-pro` by default).
If `ICODE_E2E_API_KEY` (or a preset’s `api_key_env`) is unset, LLM tests are **skipped** with a reminder.

## Smoke (SDK import)

```bash
make smoke
# or
uv run python -c "from openjiuwen.harness import create_deep_agent; from openjiuwen_icode import __version__; print(__version__)"
```
