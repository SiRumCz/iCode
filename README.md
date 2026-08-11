# OpenJiuWen iCode

Terminal coding assistant (CLI / Textual TUI / ACP) built on the
[`openjiuwen`](https://gitcode.com/openJiuwen/agent-core) SDK
(DeepAgent + tools + session runtime).

Repo: [`michaelling/iCode`](https://gitcode.com/michaelling/iCode)
(PyPI / distribution name remains `openjiuwen-icode`).

## Install

```bash
# With a published SDK + product wheel:
pip install openjiuwen-icode

# From this repo (SDK comes from the michaelling/agent-core fork, branch icode):
cd iCode
uv sync
```

`[tool.uv.sources]` points `openjiuwen` at
`ssh://git@gitcode.com/michaelling/agent-core.git` (`branch = "icode"`);
`uv.lock` pins the resolved commit. For local joint edits of the SDK:

```bash
uv add --editable ../agent-core   # do not commit the path override
```

After SDK changes land on `origin/icode`, refresh the pin:

```bash
uv lock --upgrade-package openjiuwen
```

## Run

```bash
icode --help
# or (same entry point)
openjiuwen --help
openjiuwen tui
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
- **agent-core:** `openjiuwen.core` + `openjiuwen.harness` (DeepAgent, tools, rails).
- Supported SDK import surface: `docs/design/icode-sdk-api-surface.md`.
- Compatibility: `openjiuwen.harness.cli` in agent-core is a deprecated
  shim that re-exports this package when installed.

## Tests

```bash
make test
# or
uv run pytest tests/cli/unit -q
```

## Smoke (SDK import)

```bash
uv run python -c "from openjiuwen.harness import create_deep_agent; from openjiuwen_icode import __version__; print(__version__)"
```
