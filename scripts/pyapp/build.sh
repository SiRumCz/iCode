#!/usr/bin/env bash
# Build a self-contained icode binary for the current (or --target) platform
# using PyApp. Mirrors Chrys scripts/build.sh.
#
# Prerequisites: Rust (cargo, rustup), curl, perl
#                uv (preferred) or python3 + build
#                Linux musl targets: musl-tools (apt install musl-tools)
#
# Usage:
#   ./scripts/pyapp/build.sh
#   ./scripts/pyapp/build.sh --uv
#   ./scripts/pyapp/build.sh --target x86_64-unknown-linux-musl
#   ./scripts/pyapp/build.sh --skip-wheel   # reuse dist/*.whl
#
# Environment:
#   PYAPP_VERSION, PYAPP_PYTHON_VERSION, PYAPP_PROJECT_FEATURES
#   PYAPP_SOURCE   — local PyApp source.tar.gz
#   PYTHON_DIST    — local python-build-standalone tarball
#   PROJECT_VERSION — override version stamped into the binary
#
# Output: dist/icode  (or dist/icode.exe on Windows)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

USE_UV=false
SKIP_WHEEL=false
TARGET=""

usage() {
    cat <<'EOF'
Usage: build.sh [--uv] [--skip-wheel] [--target <rust-triple>]

  --uv            Use uv as the first-run installer (default: pip)
  --skip-wheel    Do not rebuild; use existing dist/*.whl
  --target TRIPLE Cargo target (default: host; Linux defaults to *-musl)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --uv) USE_UV=true; shift ;;
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

pyapp_require_cmd curl perl cargo
if [[ "$SKIP_WHEEL" != "true" ]]; then
    if ! command -v uv >/dev/null 2>&1 && ! python3 -c "import build" 2>/dev/null; then
        pyapp_die "need uv, or python3 with the 'build' package, to produce a wheel"
    fi
fi

VERSION="$(pyapp_project_version)"
pyapp_log "Building ${BINARY_BASENAME} v${VERSION} (PyApp v${PYAPP_VERSION}, Python ${PYAPP_PYTHON_VERSION})"

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
pyapp_export_build_env "$VERSION" "$WHEEL" "$USE_UV"

if [[ -z "$TARGET" ]]; then
    TARGET="$(pyapp_default_target)"
fi

if [[ -n "$TARGET" ]]; then
    pyapp_maybe_override_musl_python "$TARGET"
fi

pyapp_log "Compiling binary..."
mkdir -p "$PROJECT_ROOT/dist"
if [[ -n "$TARGET" ]]; then
    pyapp_log "Target: $TARGET"
    if [[ "$TARGET" == *-musl ]]; then
        if ! command -v musl-gcc >/dev/null 2>&1 && ! command -v x86_64-linux-musl-gcc >/dev/null 2>&1; then
            echo "Warning: musl gcc not found; install musl-tools or use Docker (scripts/pyapp/build-multi.sh)" >&2
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
if [[ "$BUILD_OS" == MINGW* || "$BUILD_OS" == MSYS* || "$BUILD_OS" == CYGWIN* ]] \
    || [[ "$TARGET" == *windows* ]]; then
    OUTPUT="$PROJECT_ROOT/dist/${BINARY_BASENAME}.exe"
    cp "$RELEASE_DIR/pyapp.exe" "$OUTPUT"
else
    OUTPUT="$PROJECT_ROOT/dist/${BINARY_BASENAME}"
    cp "$RELEASE_DIR/pyapp" "$OUTPUT"
    chmod +x "$OUTPUT"
fi

# Also keep a platform-tagged copy for release packaging.
STEM="$(pyapp_artifact_stem "$TARGET")"
if [[ "$STEM" == *.exe ]]; then
    TAGGED="$PROJECT_ROOT/dist/${STEM%.exe}-v${VERSION}.exe"
else
    TAGGED="$PROJECT_ROOT/dist/${STEM}-v${VERSION}"
fi
cp "$OUTPUT" "$TAGGED"
chmod +x "$TAGGED" 2>/dev/null || true

SIZE="$(du -h "$OUTPUT" | cut -f1)"
pyapp_log "Done: $OUTPUT ($SIZE)"
pyapp_log "Tagged: $TAGGED"
if [[ "$USE_UV" == "true" ]]; then
    echo "    First run: uv installs deps from PyPI (set UV_INDEX_URL for mirrors)"
else
    echo "    First run: pip installs deps from PyPI (set PIP_INDEX_URL for mirrors)"
fi
