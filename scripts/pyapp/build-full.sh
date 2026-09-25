#!/usr/bin/env bash
# Build a self-contained icode binary with *all* dependencies preinstalled
# (offline at runtime). Uses PyApp's recommended approach:
#   1. Fetch python-build-standalone
#   2. pip/uv-install openjiuwen[features] + deps into that prefix
#   3. Re-archive and embed with PYAPP_SKIP_INSTALL=true
#
# Output is named with "-full" so it is distinct from the slim PyApp binary:
#   dist/icode-<os>-<arch>-full-v<ver>
#
# Prerequisites: Rust (cargo), curl, perl, uv (recommended) or pip
# Build-time network is required to download CPython + third-party wheels.
#
# Usage:
#   ./scripts/pyapp/build-full.sh
#   ./scripts/pyapp/build-full.sh --target aarch64-apple-darwin
#   ./scripts/pyapp/build-full.sh --skip-wheel
#
# Environment: same as build.sh (PYAPP_VERSION, PYAPP_PYTHON_VERSION,
# PYAPP_PROJECT_FEATURES, UV_INDEX_URL / PIP_INDEX_URL, …)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

SKIP_WHEEL=false
TARGET=""

usage() {
    cat <<'EOF'
Usage: build-full.sh [--skip-wheel] [--target <rust-triple>]

  Build a full-deps (offline-at-runtime) PyApp binary.
  Artifact name includes "-full" (e.g. icode-macos-aarch64-full-v0.1.19).
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-wheel) SKIP_WHEEL=true; shift ;;
        --target)
            [[ $# -ge 2 ]] || pyapp_die "--target requires a value"
            TARGET="$2"
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *) pyapp_die "unknown argument: $1 (see --help)" ;;
    esac
done

pyapp_require_cmd curl perl cargo tar
if [[ "$SKIP_WHEEL" != "true" ]]; then
    if ! command -v uv >/dev/null 2>&1 && ! python3 -c "import build" 2>/dev/null; then
        pyapp_die "need uv, or python3 with the 'build' package, to produce a wheel"
    fi
fi
command -v uv >/dev/null 2>&1 || pyapp_die "uv is required to install deps into the embedded CPython for full builds"

VERSION="$(pyapp_project_version)"
pyapp_log "Building ${BINARY_BASENAME} FULL v${VERSION} (PyApp v${PYAPP_VERSION}, Python ${PYAPP_PYTHON_VERSION})"
pyapp_log "Features: ${PYAPP_PROJECT_FEATURES} (all third-party deps baked in; large artifact)"

if [[ "$SKIP_WHEEL" != "true" ]]; then
    pyapp_build_wheel
fi
WHEEL_SOURCE="$(pyapp_resolve_wheel "$VERSION")"

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

pyapp_fetch_source "$BUILD_DIR"
PYAPP_DIR="$BUILD_DIR/pyapp-v${PYAPP_VERSION}"
cp "$WHEEL_SOURCE" "$PYAPP_DIR/"
cd "$PYAPP_DIR"

WHEEL="$(basename "$WHEEL_SOURCE")"
pyapp_apply_patches "$PYAPP_DIR"

if [[ -z "$TARGET" ]]; then
    TARGET="$(pyapp_default_target)"
fi

CPYTHON_TRIPLE="$(pyapp_cpython_triple "$TARGET")"
CPYTHON_URL="$(pyapp_resolve_cpython_url "$PYAPP_DIR/build.rs" "$CPYTHON_TRIPLE")"
pyapp_log "CPython standalone: $CPYTHON_URL"

DIST_ROOT="$BUILD_DIR/dist-root"
mkdir -p "$DIST_ROOT"
pyapp_log "Downloading and extracting CPython..."
curl -fL --retry 3 --retry-delay 2 "$CPYTHON_URL" | tar -xz -C "$DIST_ROOT"

# install_only_stripped layouts use a top-level "python/" directory.
PYTHON_PREFIX="$DIST_ROOT/python"
[[ -d "$PYTHON_PREFIX" ]] || pyapp_die "expected $PYTHON_PREFIX after extracting standalone build"
if [[ -x "$PYTHON_PREFIX/bin/python3" ]]; then
    PYTHON_BIN="$PYTHON_PREFIX/bin/python3"
    DIST_PYTHON_PATH="python/bin/python3"
elif [[ -x "$PYTHON_PREFIX/python.exe" ]]; then
    PYTHON_BIN="$PYTHON_PREFIX/python.exe"
    DIST_PYTHON_PATH="python/python.exe"
else
    pyapp_die "could not find python binary under $PYTHON_PREFIX"
fi

# Build-time install (needs network / mirror + git SSH for openjiuwen fork).
# Runtime will PYAPP_SKIP_INSTALL.
WHEEL_ABS="${PYAPP_DIR}/${WHEEL}"
pyapp_install_full_runtime "$PYTHON_BIN" "$WHEEL_ABS" "$BUILD_DIR"

pyapp_log "Re-archiving preinstalled distribution..."
DIST_ARCHIVE="$PYAPP_DIR/icode-full-python.tar.gz"
tar -czf "$DIST_ARCHIVE" -C "$DIST_ROOT" python

# Configure PyApp for offline runtime (no pip install on first launch).
export PYAPP_PROJECT_NAME
export PYAPP_PROJECT_VERSION="$VERSION"
# Keep project path for metadata; installation is skipped.
export PYAPP_PROJECT_PATH="$WHEEL"
export PYAPP_PROJECT_FEATURES
export PYAPP_PYTHON_VERSION
export PYAPP_EXEC_SPEC
export PYAPP_SELF_COMMAND="${PYAPP_SELF_COMMAND:-self}"
export PYAPP_PASS_LOCATION="${PYAPP_PASS_LOCATION:-true}"
export PYAPP_DISTRIBUTION_EMBED=true
export PYAPP_DISTRIBUTION_PATH
PYAPP_DISTRIBUTION_PATH="$(basename "$DIST_ARCHIVE")"
export PYAPP_DISTRIBUTION_PYTHON_PATH="$DIST_PYTHON_PATH"
export PYAPP_SKIP_INSTALL=true
# Avoid creating a second empty venv; run from the prefilled prefix.
export PYAPP_FULL_ISOLATION=true
unset PYAPP_UV_ENABLED PYAPP_DISTRIBUTION_PIP_AVAILABLE PYAPP_PIP_EXTRA_ARGS || true

pyapp_log "Compiling FULL binary..."
mkdir -p "$PROJECT_ROOT/dist"
if [[ -n "$TARGET" ]]; then
    pyapp_log "Target: $TARGET"
    if [[ "$TARGET" == *-musl ]]; then
        if ! command -v musl-gcc >/dev/null 2>&1 && ! command -v x86_64-linux-musl-gcc >/dev/null 2>&1; then
            echo "Warning: musl gcc not found; prefer Docker via build-multi.sh --full" >&2
        fi
    fi
    rustup target add "$TARGET" 2>/dev/null || true
    cargo build --release --target "$TARGET"
    RELEASE_DIR="target/$TARGET/release"
else
    cargo build --release
    RELEASE_DIR="target/release"
fi

BUILD_OS="$(uname -s)"
STEM_FULL="$(pyapp_artifact_stem_full "$TARGET")"
if [[ "$BUILD_OS" == MINGW* || "$BUILD_OS" == MSYS* || "$BUILD_OS" == CYGWIN* ]] \
    || [[ "$TARGET" == *windows* ]]; then
    OUTPUT="$PROJECT_ROOT/dist/${BINARY_BASENAME}-full.exe"
    cp "$RELEASE_DIR/pyapp.exe" "$OUTPUT"
    TAGGED="$PROJECT_ROOT/dist/${STEM_FULL%.exe}-v${VERSION}.exe"
else
    OUTPUT="$PROJECT_ROOT/dist/${BINARY_BASENAME}-full"
    cp "$RELEASE_DIR/pyapp" "$OUTPUT"
    chmod +x "$OUTPUT"
    TAGGED="$PROJECT_ROOT/dist/${STEM_FULL}-v${VERSION}"
fi
cp "$OUTPUT" "$TAGGED"
chmod +x "$TAGGED" 2>/dev/null || true

SIZE="$(du -h "$OUTPUT" | cut -f1)"
pyapp_log "Done FULL: $OUTPUT ($SIZE)"
pyapp_log "Tagged: $TAGGED"
echo "    Runtime: offline (deps preinstalled; no PyPI on first launch)"
