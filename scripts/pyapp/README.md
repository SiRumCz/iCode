# iCode PyApp packaging

Build standalone `icode` binaries (embedded CPython + wheel) with
[PyApp](https://github.com/ofek/pyapp), following Chrys `scripts/build.sh` /
`.github/workflows/cd.yml`.

User-facing name is **icode**. The pip project / import path remain
`openjiuwen-icode` / `openjiuwen_icode` (SDK dependency is still `openjiuwen`).

## Quick start (current machine)

```bash
# Prerequisites: rustup + cargo, curl, perl, uv (recommended)
./scripts/pyapp/build.sh
# → dist/icode  (+ version-tagged copy)
```

Optional:

```bash
./scripts/pyapp/build.sh --uv
./scripts/pyapp/build.sh --target x86_64-unknown-linux-musl
```

## Release (version bump + macOS/Linux packages)

```bash
# Bump patch, unify CLI + VS Code extension versions, commit, tag, push, build
./scripts/pyapp/release.sh

# Keep current version (no bump commit); still tag HEAD as vX.Y.Z and push
# (requires pyproject and extensions/vscode-icode versions already equal)
./scripts/pyapp/release.sh --no-bump

# Also build full-deps offline binaries (name contains -full-)
./scripts/pyapp/release.sh --no-bump --full
./scripts/pyapp/build-full.sh                  # current host only
./scripts/pyapp/build-multi.sh --full --package

# Set an exact version
./scripts/pyapp/release.sh --version 0.2.0

# Version/tag/push only (no binaries)
./scripts/pyapp/release.sh --skip-build
./scripts/pyapp/release.sh --no-bump --skip-build --no-push   # local tag only
```

After binaries are collected, `release.sh` asks whether to upload them as a
**GitCode + GitHub** release for `vX.Y.Z` (or use `--publish` / `--no-publish`).
The two uploads run **concurrently** in the background (default wall-clock
timeout **10 minutes**, overridable with `--publish-timeout SEC` or
`PUBLISH_TIMEOUT_SEC`). On timeout remaining jobs are killed and a warning is
printed; local artifacts under `dist/release/` are kept.

```bash
export GITCODE_TOKEN=...   # GitCode PAT with release permissions
# GitHub: gh auth login   # or export GH_TOKEN=...
./scripts/pyapp/release.sh --no-bump --full --publish
# or republish existing artifacts:
./scripts/pyapp/publish-gitcode-release.sh 0.1.21 dist/release
./scripts/pyapp/publish-github-release.sh 0.1.21 dist/release
```

Remotes: `origin` = GitCode (primary / development), `github` = mirror for sync
and GitHub Releases. `release.sh` pushes HEAD and all tags to both.

| Artifact name | Meaning |
|---------------|---------|
| `icode-<os>-<arch>-v<ver>.tar.gz` | Slim PyApp; first run installs deps from PyPI |
| `icode-<os>-<arch>-full-v<ver>.tar.gz` | Full offline; deps preinstalled at build time |

Artifacts land in `dist/release/` (override with `--out-dir`). Windows is not
built here. On a Mac with Docker you typically get macOS (native) + Linux
(Docker); on Linux-only hosts macOS targets are skipped.

End-user instructions are in [`使用说明.md`](./使用说明.md). That file is
copied into `dist/release/` and into each `.tar.gz` / `.zip` next to the
`icode` binary.

`release.sh` bumps `pyproject.toml` / CLI `__version__` / the local
`openjiuwen` entry in `uv.lock` **offline** (no full `uv lock` network
resolve), then builds macOS + Linux packages.

Pinned defaults (override via env):

| Variable | Default | Notes |
|----------|---------|--------|
| `PYAPP_VERSION` | `0.29.0` | PyApp release |
| `PYAPP_PYTHON_VERSION` | `3.13` | Must be `<3.14` (see `requires-python`) |
| `PYAPP_PROJECT_FEATURES` | `tui` | Extra features installed on first run |
| `BINARY_BASENAME` | `icode` | User-facing binary / archive prefix |
| `PYAPP_PROJECT_NAME` | `openjiuwen-icode` | Wheel / pip project name |

First run of the binary still downloads project dependencies from PyPI into the
embedded env (`PIP_INDEX_URL` / `UV_INDEX_URL` for mirrors).

## Multi-platform: do we need Docker?

**Partially.** Same split as Chrys CD:

| Target | How to build | Docker? |
|--------|----------------|---------|
| Linux x86_64 / aarch64 (musl binary, glibc CPython embed) | `build-multi.sh` via Docker, or native Linux + `musl-tools` | **Yes (recommended)** for reproducible Linux builds from any Docker host. On Apple Silicon, `linux/amd64` is built as a separate image tag and runs under qemu. |
| macOS arm64 / x86_64 | Native macOS (CI `macos-latest`) | **No** — Apple SDK; Linux Docker cannot ship real macOS binaries |
| Windows x86_64 | Native Windows (CI `windows-latest`) | **No** in these scripts — Wine/`cross` is fragile; use a Windows runner |

```bash
# From a machine with Docker: build Linux targets; skip foreign OS with a message
./scripts/pyapp/build-multi.sh --platform linux --package

# On a Mac: also produce macOS binaries
./scripts/pyapp/build-multi.sh --platform macos --package

# Everything this host can reach (Linux via Docker + native macOS/Windows)
./scripts/pyapp/build-multi.sh --package
```

For a full five-platform GitHub Release, use a CI matrix with native
`ubuntu` / `macos` / `windows` runners (Chrys `cd.yml` pattern), and call
`scripts/pyapp/build.sh --target …` on each. Docker alone is not enough for
macOS/Windows artifacts.

## Outputs

| Path | Meaning |
|------|---------|
| `dist/icode` | Host binary name |
| `dist/icode-<os>-<arch>-v<ver>` | Tagged binary |
| `dist/release/*.tar.gz` / `*.zip` | With `--package` |
| `dist/release/*.whl` | Wheel copied into the release dir |
| `dist/release/icode-<ver>.vsix` | VS Code extension (same version) |
| `dist/release/SHA256SUMS.txt` | Checksums |

## Entry point

PyApp `PYAPP_EXEC_SPEC` defaults to
`openjiuwen_icode.cli:pyapp_main` (Click CLI with preserved exit codes).
