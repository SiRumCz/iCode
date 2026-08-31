#!/usr/bin/env bash
# Shared helpers for iCode PyApp packaging (sourced by other scripts).
# Style and env vars follow Chrys scripts/build.sh + .github/workflows/cd.yml.
#
# User-facing release name is ``icode`` (binary + archive prefix).
# Pip project / import path stay ``openjiuwen-icode`` / ``openjiuwen_icode``.

set -euo pipefail

PYAPP_VERSION="${PYAPP_VERSION:-0.29.0}"
# Must stay within openjiuwen requires-python (>=3.11,<3.14).
PYAPP_PYTHON_VERSION="${PYAPP_PYTHON_VERSION:-3.13}"
PYAPP_PROJECT_NAME="${PYAPP_PROJECT_NAME:-openjiuwen-icode}"
PYAPP_PROJECT_FEATURES="${PYAPP_PROJECT_FEATURES:-}"
PYAPP_EXEC_SPEC="${PYAPP_EXEC_SPEC:-openjiuwen_icode.cli:pyapp_main}"
BINARY_BASENAME="${BINARY_BASENAME:-icode}"

_pyapp_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$_pyapp_script_dir/../.." && pwd)"

pyapp_log() {
    echo "==> $*" >&2
}

pyapp_die() {
    echo "Error: $*" >&2
    exit 1
}

pyapp_require_cmd() {
    local cmd
    for cmd in "$@"; do
        command -v "$cmd" >/dev/null 2>&1 || pyapp_die "missing required command: $cmd"
    done
}

pyapp_project_version() {
    if [[ -n "${PROJECT_VERSION:-}" ]]; then
        echo "$PROJECT_VERSION"
        return
    fi
    (
        cd "$PROJECT_ROOT"
        if command -v uv >/dev/null 2>&1; then
            uv run python -c "
import tomllib, pathlib
print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])
"
        else
            python3 -c "
import tomllib, pathlib
print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])
"
        fi
    )
}

pyapp_build_wheel() {
    pyapp_log "Building wheel..."
    (
        cd "$PROJECT_ROOT"
        if command -v uv >/dev/null 2>&1; then
            uv build --wheel --quiet
        else
            python3 -m build --wheel
        fi
    )
}

pyapp_install_full_runtime() {
    # Install the same runtime closure as ``uv sync`` into an embedded CPython
    # prefix, then overlay the local product wheel without re-resolving deps.
    #
    # Args: PYTHON_BIN WHEEL_ABS WORK_DIR
    #
    # ``uv pip install <wheel>`` alone pulls ``openjiuwen`` from PyPI (often a
    # newer build than the git fork in pyproject/uv.lock) and can miss optional
    # imports such as ``opentelemetry.sdk``. Prefer uv.lock when present.
    local python_bin="$1"
    local wheel_abs="$2"
    local work_dir="$3"
    local req_file="$work_dir/full-requirements.txt"
    local lock_file="$PROJECT_ROOT/uv.lock"

    if [[ -f "$lock_file" ]]; then
        pyapp_log "Installing locked runtime deps from uv.lock into embedded CPython..."
        (
            cd "$PROJECT_ROOT"
            uv export --frozen --no-dev --no-emit-project --no-hashes -o "$req_file"
        )
        uv pip install --python "$python_bin" -r "$req_file"
        pyapp_log "Installing ${PYAPP_PROJECT_NAME} wheel (no-deps overlay)..."
        uv pip install --python "$python_bin" --no-deps "$wheel_abs"
        return 0
    fi

    echo "Warning: uv.lock missing; falling back to wheel-only install (openjiuwen may come from PyPI)." >&2
    if [[ -n "${PYAPP_PROJECT_FEATURES}" ]]; then
        uv pip install --python "$python_bin" \
            "${PYAPP_PROJECT_NAME}[${PYAPP_PROJECT_FEATURES}] @ ${wheel_abs}"
    else
        uv pip install --python "$python_bin" "$wheel_abs"
    fi
}

pyapp_resolve_wheel() {
    # Wheel filenames normalize hyphens in the dist name to underscores
    # (PEP 427), e.g. openjiuwen-icode → openjiuwen_icode-…-py3-none-any.whl.
    local version="$1"
    local name_hyphen="$PYAPP_PROJECT_NAME"
    local name_under="${PYAPP_PROJECT_NAME//-/_}"
    local preferred found

    for preferred in \
        "$PROJECT_ROOT/dist/${name_under}-${version}-py3-none-any.whl" \
        "$PROJECT_ROOT/dist/${name_hyphen}-${version}-py3-none-any.whl"
    do
        if [[ -f "$preferred" ]]; then
            echo "$preferred"
            return 0
        fi
    done

    found="$(
        ls -t \
            "$PROJECT_ROOT"/dist/"${name_under}"-*.whl \
            "$PROJECT_ROOT"/dist/"${name_hyphen}"-*.whl \
            2>/dev/null | head -1 || true
    )"
    [[ -n "$found" ]] || pyapp_die "no wheel found under dist/; run build wheel first"
    echo "$found"
}

pyapp_fetch_source() {
    # Args: DEST_DIR — extracts PyApp into DEST_DIR/pyapp-v${PYAPP_VERSION}
    local dest="$1"
    mkdir -p "$dest"
    if [[ -n "${PYAPP_SOURCE:-}" ]]; then
        pyapp_log "Using local PyApp source: $PYAPP_SOURCE"
        tar xzf "$PYAPP_SOURCE" -C "$dest"
    else
        pyapp_log "Downloading PyApp v${PYAPP_VERSION}..."
        local url="https://github.com/ofek/pyapp/releases/download/v${PYAPP_VERSION}/source.tar.gz"
        if command -v gh >/dev/null 2>&1 \
            && gh release download "v${PYAPP_VERSION}" \
                --repo ofek/pyapp --pattern source.tar.gz --dir "$dest" 2>/dev/null; then
            tar xzf "$dest/source.tar.gz" -C "$dest"
        else
            curl -fsSL "$url" | tar xz -C "$dest"
        fi
    fi
    [[ -d "$dest/pyapp-v${PYAPP_VERSION}" ]] \
        || pyapp_die "PyApp source not found at $dest/pyapp-v${PYAPP_VERSION}"
}

pyapp_apply_patches() {
    # Args: PYAPP_DIR
    local dir="$1"
    (
        cd "$dir"
        # Tolerate non-UTF-8 subprocess output (non-English Windows locales).
        pyapp_log "Patching PyApp UTF-8 subprocess handling..."
        perl -i -pe '
          s/let mut output = String::new\(\);/let mut raw = Vec::new();/;
          s/reader\.read_to_string\(\&mut output\)\?;/reader.read_to_end(\&mut raw)?;/;
          s/Ok\(\(result\?, output\)\)/let output = String::from_utf8_lossy(\&raw).into_owned();\n    Ok((result?, output))/;
        ' src/process.rs

        # Large CPython + wheel downloads often exceed the default 30s timeout.
        pyapp_log "Patching PyApp download timeout (300s)..."
        perl -i -pe '
          s/reqwest::blocking::get\(([^)]+)\)/reqwest::blocking::Client::builder().timeout(std::time::Duration::from_secs(300)).build().unwrap().get($1).send()/g;
        ' build.rs
    )
}

pyapp_export_build_env() {
    # Args: VERSION WHEEL_BASENAME USE_UV(true|false)
    local version="$1"
    local wheel_base="$2"
    local use_uv="$3"

    export PYAPP_PROJECT_NAME
    export PYAPP_PROJECT_VERSION="$version"
    export PYAPP_PROJECT_PATH="$wheel_base"
    export PYAPP_PROJECT_FEATURES
    export PYAPP_PYTHON_VERSION
    export PYAPP_EXEC_SPEC
    export PYAPP_SELF_COMMAND="${PYAPP_SELF_COMMAND:-self}"
    export PYAPP_PASS_LOCATION="${PYAPP_PASS_LOCATION:-true}"
    export PYAPP_PIP_ALLOW_CONFIG="${PYAPP_PIP_ALLOW_CONFIG:-true}"
    export PYAPP_DISTRIBUTION_EMBED="${PYAPP_DISTRIBUTION_EMBED:-true}"

    unset PYAPP_UV_ENABLED PYAPP_FULL_ISOLATION PYAPP_DISTRIBUTION_PIP_AVAILABLE || true
    if [[ "$use_uv" == "true" ]]; then
        pyapp_log "Installer: uv"
        export PYAPP_UV_ENABLED=true
    else
        pyapp_log "Installer: pip (full isolation)"
        export PYAPP_FULL_ISOLATION=true
        export PYAPP_DISTRIBUTION_PIP_AVAILABLE=true
    fi

    if [[ -n "${PYTHON_DIST:-}" ]]; then
        pyapp_log "Using local Python distribution: $PYTHON_DIST"
        cp "$PYTHON_DIST" .
        export PYAPP_DISTRIBUTION_PATH
        PYAPP_DISTRIBUTION_PATH="$(basename "$PYTHON_DIST")"
        case "$(uname -s)" in
            MINGW*|MSYS*|CYGWIN*)
                export PYAPP_DISTRIBUTION_PYTHON_PATH="python/python.exe"
                ;;
            *)
                export PYAPP_DISTRIBUTION_PYTHON_PATH="python/bin/python3"
                ;;
        esac
    fi
}

pyapp_maybe_override_musl_python() {
    # When targeting musl, prefer embedding the glibc CPython so the extracted
    # interpreter works on typical Linux desktops/servers (same as Chrys CD).
    local target="${1:-}"
    [[ "$target" == *-musl ]] || return 0
    local gnu_arch="${target%%-unknown-linux-musl}"
    local gnu_url
    gnu_url="$(
        grep -o "https://[^\"]*${gnu_arch}-unknown-linux-gnu-install_only_stripped[^\"]*" build.rs \
            | grep "cpython-${PYAPP_PYTHON_VERSION}" | head -1 || true
    )"
    if [[ -n "$gnu_url" ]]; then
        gnu_url="${gnu_url//%2B/+}"
        export PYAPP_DISTRIBUTION_SOURCE="$gnu_url"
        pyapp_log "Overriding Python distribution: glibc for ${gnu_arch}"
    else
        echo "Warning: no glibc distribution URL for ${gnu_arch}; using PyApp default" >&2
    fi
}

pyapp_default_target() {
    # Echo a cargo target for static Linux builds; empty for host default.
    case "$(uname -s)-$(uname -m)" in
        Linux-x86_64) echo "x86_64-unknown-linux-musl" ;;
        Linux-aarch64|Linux-arm64) echo "aarch64-unknown-linux-musl" ;;
        *) echo "" ;;
    esac
}

pyapp_usage_doc() {
    # Path to the end-user usage guide shipped with release binaries.
    echo "$_pyapp_script_dir/使用说明.md"
}

pyapp_stage_usage_doc() {
    # Copy 使用说明.md into DIR (for dist/release and archive staging).
    local dest_dir="$1"
    local src
    src="$(pyapp_usage_doc)"
    [[ -f "$src" ]] || pyapp_die "missing usage doc: $src"
    mkdir -p "$dest_dir"
    cp -f "$src" "$dest_dir/使用说明.md"
}

pyapp_artifact_stem() {
    # Map cargo target → release artifact basename (without version/installer).
    local target="$1"
    case "$target" in
        x86_64-unknown-linux-musl) echo "${BINARY_BASENAME}-linux-x86_64" ;;
        aarch64-unknown-linux-musl) echo "${BINARY_BASENAME}-linux-aarch64" ;;
        aarch64-apple-darwin) echo "${BINARY_BASENAME}-macos-aarch64" ;;
        x86_64-apple-darwin) echo "${BINARY_BASENAME}-macos-x86_64" ;;
        x86_64-pc-windows-msvc|x86_64-pc-windows-gnu)
            echo "${BINARY_BASENAME}-windows-x86_64.exe"
            ;;
        "")
            case "$(uname -s)-$(uname -m)" in
                Darwin-arm64|Darwin-aarch64) echo "${BINARY_BASENAME}-macos-aarch64" ;;
                Darwin-x86_64) echo "${BINARY_BASENAME}-macos-x86_64" ;;
                Linux-x86_64) echo "${BINARY_BASENAME}-linux-x86_64" ;;
                Linux-aarch64|Linux-arm64) echo "${BINARY_BASENAME}-linux-aarch64" ;;
                MINGW*|MSYS*|CYGWIN*) echo "${BINARY_BASENAME}-windows-x86_64.exe" ;;
                *) echo "${BINARY_BASENAME}-$(uname -s)-$(uname -m)" ;;
            esac
            ;;
        *) echo "${BINARY_BASENAME}-${target}" ;;
    esac
}

pyapp_artifact_stem_full() {
    # Full-deps variant: insert "-full" before optional .exe
    local stem
    stem="$(pyapp_artifact_stem "$1")"
    if [[ "$stem" == *.exe ]]; then
        echo "${stem%.exe}-full.exe"
    else
        echo "${stem}-full"
    fi
}

# Map cargo / packaging target → python-build-standalone triple used in PyApp URLs.
# Linux musl *Rust* targets still embed a glibc (gnu) CPython for end users.
pyapp_cpython_triple() {
    local target="$1"
    if [[ -z "$target" ]]; then
        target="$(pyapp_default_target)"
        if [[ -z "$target" ]]; then
            case "$(uname -s)-$(uname -m)" in
                Darwin-arm64|Darwin-aarch64) target="aarch64-apple-darwin" ;;
                Darwin-x86_64) target="x86_64-apple-darwin" ;;
                Linux-x86_64) target="x86_64-unknown-linux-gnu" ;;
                Linux-aarch64|Linux-arm64) target="aarch64-unknown-linux-gnu" ;;
                *) pyapp_die "cannot infer cpython triple for $(uname -s)-$(uname -m)" ;;
            esac
            echo "$target"
            return
        fi
    fi
    case "$target" in
        x86_64-unknown-linux-musl|x86_64-unknown-linux-gnu) echo "x86_64-unknown-linux-gnu" ;;
        aarch64-unknown-linux-musl|aarch64-unknown-linux-gnu) echo "aarch64-unknown-linux-gnu" ;;
        aarch64-apple-darwin) echo "aarch64-apple-darwin" ;;
        x86_64-apple-darwin) echo "x86_64-apple-darwin" ;;
        x86_64-pc-windows-msvc|x86_64-pc-windows-gnu) echo "x86_64-pc-windows-msvc" ;;
        *) pyapp_die "unsupported cpython triple for target: $target" ;;
    esac
}

pyapp_resolve_cpython_url() {
    # Args: path-to-pyapp-build.rs  cpython-triple
    # Echoes a python-build-standalone install_only_stripped URL for PYAPP_PYTHON_VERSION.
    local build_rs="$1"
    local triple="$2"
    local url
    url="$(
        grep -o "https://[^\"]*${triple}-install_only_stripped[^\"]*" "$build_rs" \
            | grep "cpython-${PYAPP_PYTHON_VERSION}" | head -1 || true
    )"
    [[ -n "$url" ]] || pyapp_die "no cpython ${PYAPP_PYTHON_VERSION} URL for ${triple} in ${build_rs}"
    echo "${url//%2B/+}"
}

pyapp_host_can_build_target() {
    local target="$1"
    case "$target" in
        x86_64-unknown-linux-musl|aarch64-unknown-linux-musl)
            [[ "$(uname -s)" == "Linux" ]] && return 0
            return 1
            ;;
        aarch64-apple-darwin|x86_64-apple-darwin)
            [[ "$(uname -s)" == "Darwin" ]] && return 0
            return 1
            ;;
        x86_64-pc-windows-msvc|x86_64-pc-windows-gnu)
            case "$(uname -s)" in
                MINGW*|MSYS*|CYGWIN*) return 0 ;;
                *) return 1 ;;
            esac
            ;;
        *) return 1 ;;
    esac
}
