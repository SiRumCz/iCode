# iCode

Terminal coding assistant (CLI / Textual TUI / ACP) built on the
[`openjiuwen`](https://gitcode.com/openJiuwen/agent-core) SDK
(DeepAgent + tools + session runtime).

Repo: [`michaelling/iCode`](https://gitcode.com/michaelling/iCode)
(PyPI / distribution name remains `openjiuwen-icode`; user-facing CLI
and release binaries are **`icode`**).

This product currently depends on the
[`michaelling/agent-core`](https://gitcode.com/michaelling/agent-core) fork,
branch `icode` (not upstream `main` / PyPI alone).

## Install

### From source (development)

```bash
# From this repo (resolves openjiuwen from the fork via [tool.uv.sources]):
cd iCode
uv sync   # requires SSH access to gitcode.com:michaelling/agent-core
```

`[tool.uv.sources]` points `openjiuwen` at
`ssh://git@gitcode.com/michaelling/agent-core.git` (`branch = "icode"`);
`uv.lock` pins the resolved commit.

### Release packages (no local Python)

GitCode Releases publish standalone **`icode`** binaries (and related assets).
You do **not** need a system Python install.

| Artifact | What it is | When to use |
|----------|------------|-------------|
| `icode-<os>-<arch>-full-vX.Y.Z.tar.gz` | **Full** offline binary: CPython + product wheel + all third-party deps baked in | **Recommended** for end users / air-gapped hosts |
| `icode-<os>-<arch>-vX.Y.Z.tar.gz` | **Slim** binary: CPython + product wheel only; first launch installs deps from PyPI | Smaller download when you have reliable network |
| `openjiuwen_icode-*-py3-none-any.whl` | Pip wheel | Developers who already manage a Python env |
| `icode-X.Y.Z.vsix` | VS Code / OpenVSX extension | Editor integration (same version as the CLI) |
| `SHA256SUMS.txt` | Checksums | Verify downloads |
| `使用说明.md` | End-user guide (also inside each `.tar.gz`) | How to pick / run a package |

Platform tokens in the filename: `linux-x86_64`, `linux-aarch64`, `macos-aarch64`, `macos-x86_64`.

**Prefer the `-full-` archive.** Slim first-run talks to PyPI and may not match this repo’s git-pinned `openjiuwen` fork. Full embeds the lockfile closure at build time and runs offline after unpack.

```bash
# Example (Linux x86_64 full)
tar -xzf icode-linux-x86_64-full-v0.1.38.tar.gz
./icode --help
./icode tui
```

More detail: [`scripts/pyapp/使用说明.md`](scripts/pyapp/使用说明.md) (shipped with every binary release) and packaging notes in [`scripts/pyapp/README.md`](scripts/pyapp/README.md).

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
| `extensions/vscode-icode/` | VS Code / OpenVSX extension (ACP client) |
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
make acp-smoke            # ACP initialize handshake (icode acp --demo)
make extension-test       # VS Code extension compile + unit test
make extension-package    # build extensions/vscode-icode/*.vsix
```

### VS Code extension (Route 2)

See [`extensions/vscode-icode/README.md`](extensions/vscode-icode/README.md) and
[`docs/design/vscode-acp-gaps.md`](docs/design/vscode-acp-gaps.md).

```bash
cd extensions/vscode-icode && npm install && npm run package
# Install the generated .vsix in VS Code / Cursor
# Or point community ACP Client at: icode acp
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
