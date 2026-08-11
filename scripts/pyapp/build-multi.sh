#!/usr/bin/env bash
# Multi-platform openjiuwen PyApp release builder.
#
# Strategy (same practical split as Chrys CD):
#   - Linux x86_64 / aarch64  → Docker (musl Rust target + glibc CPython embed)
#   - macOS arm64 / x86_64    → native Darwin host only (no Linux Docker)
#   - Windows x86_64          → native Windows host only (no Wine/Docker here)
#
# Usage:
#   ./scripts/pyapp/build-multi.sh                  # all reachable platforms
#   ./scripts/pyapp/build-multi.sh --platform linux
#   ./scripts/pyapp/build-multi.sh --platform macos
#   ./scripts/pyapp/build-multi.sh --targets x86_64-unknown-linux-musl
#   ./scripts/pyapp/build-multi.sh --no-docker       # skip Linux Docker targets
#   ./scripts/pyapp/build-multi.sh --package         # also write .tar.gz / .zip + SHA256SUMS
#
# Full five-platform releases are expected from CI with native runners
# (ubuntu / macos / windows), not from a single laptop + Docker alone.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

USE_UV=false
USE_DOCKER=true
DO_PACKAGE=false
BUILD_FULL=false
PLATFORM_FILTER="all"
TARGET_FILTER=""
DOCKER_IMAGE="${PYAPP_DOCKER_IMAGE:-openjiuwen-pyapp-builder:local}"

usage() {
    cat <<'EOF'
Usage: build-multi.sh [options]

  --uv                 Pass --uv through to slim PyApp builds
  --full               Also build full-deps (offline) binaries (*-full-v*)
  --no-docker          Do not use Docker for Linux targets
  --package            Archive binaries into dist/release/ (+ SHA256SUMS.txt)
  --platform NAME      all | linux | macos | windows (default: all)
  --targets LIST       Comma-separated cargo triples (overrides --platform)
  --docker-image NAME  Builder image base (default: openjiuwen-pyapp-builder:local)

Docker is only used for Linux musl targets. macOS/Windows require a matching host
or a CI matrix (see scripts/pyapp/README.md).
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --uv) USE_UV=true; shift ;;
        --full) BUILD_FULL=true; shift ;;
        --no-docker) USE_DOCKER=false; shift ;;
        --package) DO_PACKAGE=true; shift ;;
        --platform)
            [[ $# -ge 2 ]] || pyapp_die "--platform requires a value"
            PLATFORM_FILTER="$2"
            shift 2
            ;;
        --targets)
            [[ $# -ge 2 ]] || pyapp_die "--targets requires a value"
            TARGET_FILTER="$2"
            shift 2
            ;;
        --docker-image)
            [[ $# -ge 2 ]] || pyapp_die "--docker-image requires a value"
            DOCKER_IMAGE="$2"
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *) pyapp_die "unknown argument: $1 (see --help)" ;;
    esac
done

ALL_TARGETS=(
    x86_64-unknown-linux-musl
    aarch64-unknown-linux-musl
    aarch64-apple-darwin
    x86_64-apple-darwin
    x86_64-pc-windows-msvc
)

target_platform() {
    case "$1" in
        *linux*) echo linux ;;
        *apple*) echo macos ;;
        *windows*) echo windows ;;
        *) echo unknown ;;
    esac
}

select_targets() {
    local t p
    if [[ -n "$TARGET_FILTER" ]]; then
        IFS=',' read -r -a SELECTED <<< "$TARGET_FILTER"
        return
    fi
    SELECTED=()
    for t in "${ALL_TARGETS[@]}"; do
        p="$(target_platform "$t")"
        if [[ "$PLATFORM_FILTER" == "all" || "$PLATFORM_FILTER" == "$p" ]]; then
            SELECTED+=("$t")
        fi
    done
}

ensure_docker_image() {
    # Args: docker platform (e.g. linux/amd64). Echoes the image tag to use.
    # Build a per-platform tag so Apple Silicon hosts can run linux/amd64 via
    # qemu without Docker trying (and failing) to pull :local from a registry.
    local plat="$1"
    local base="${DOCKER_IMAGE%%:*}"
    local plat_tag="${plat//\//-}"
    local image="${base}:local-${plat_tag}"
    local need_build=false

    if ! docker image inspect "$image" >/dev/null 2>&1; then
        need_build=true
    elif ! docker run --rm --platform "$plat" "$image" bash -c 'command -v uv >/dev/null' 2>/dev/null; then
        pyapp_log "Docker image $image missing uv; rebuilding for full-deps support..."
        need_build=true
    fi

    if [[ "$need_build" == "true" ]]; then
        pyapp_log "Building Docker image $image ($plat)..."
        docker build --platform "$plat" -t "$image" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR"
    fi
    echo "$image"
}

docker_platform_for_target() {
    case "$1" in
        x86_64-unknown-linux-musl) echo "linux/amd64" ;;
        aarch64-unknown-linux-musl) echo "linux/arm64" ;;
        *) return 1 ;;
    esac
}

build_native() {
    local target="$1"
    local args=(--skip-wheel --target "$target")
    [[ "$USE_UV" == "true" ]] && args+=(--uv)
    "$SCRIPT_DIR/build.sh" "${args[@]}"
    if [[ "$BUILD_FULL" == "true" ]]; then
        "$SCRIPT_DIR/build-full.sh" --skip-wheel --target "$target"
    fi
}

build_linux_docker() {
    local target="$1"
    local plat image
    plat="$(docker_platform_for_target "$target")" || pyapp_die "not a docker linux target: $target"
    image="$(ensure_docker_image "$plat")"

    local version wheel_host wheel_name
    version="$(pyapp_project_version)"
    wheel_host="$(pyapp_resolve_wheel "$version")"
    wheel_name="$(basename "$wheel_host")"
    # Wheel must live under the repo mount (/src/dist/...); do not bind-mount it
    # again to /wheels and cp into dist — that is a same-file copy and fails.

    pyapp_log "Docker build $target (image=$image, platform=$plat)..."
    docker run --rm \
        --platform "$plat" \
        -e PYAPP_VERSION \
        -e PYAPP_PYTHON_VERSION \
        -e PYAPP_PROJECT_FEATURES \
        -e PYAPP_SOURCE \
        -e PYTHON_DIST \
        -e PROJECT_VERSION="$version" \
        -e UV_INDEX_URL \
        -e PIP_INDEX_URL \
        -e HOST_UID="$(id -u)" \
        -e HOST_GID="$(id -g)" \
        -v "$PROJECT_ROOT:/src:rw" \
        -w /src \
        "$image" \
        bash -c "
            set -euo pipefail
            if [[ ! -f '/src/dist/${wheel_name}' ]]; then
                echo \"Error: wheel not found in mounted dist: ${wheel_name}\" >&2
                exit 1
            fi
            export PYAPP_PROJECT_FEATURES='${PYAPP_PROJECT_FEATURES}'
            args=(--skip-wheel --target '${target}')
            if [[ '${USE_UV}' == 'true' ]]; then args+=(--uv); fi
            /src/scripts/pyapp/build.sh \"\${args[@]}\"
            if [[ '${BUILD_FULL}' == 'true' ]]; then
                /src/scripts/pyapp/build-full.sh --skip-wheel --target '${target}'
            fi
            if [[ -n \"\${HOST_UID:-}\" ]]; then
                chown -R \"\${HOST_UID}:\${HOST_GID}\" /src/dist || true
            fi
        "
}

package_releases() {
    local version release_dir f base archive
    version="$(pyapp_project_version)"
    release_dir="$PROJECT_ROOT/dist/release"
    mkdir -p "$release_dir"
    rm -f "$release_dir"/* 2>/dev/null || true

    pyapp_log "Packaging release archives into dist/release/ ..."
    pyapp_stage_usage_doc "$release_dir"

    # Prefer version-tagged binaries produced by build.sh.
    shopt -s nullglob
    for f in "$PROJECT_ROOT/dist/${BINARY_BASENAME}-"*-v"${version}" \
             "$PROJECT_ROOT/dist/${BINARY_BASENAME}-"*-v"${version}".exe; do
        [[ -f "$f" ]] || continue
        base="$(basename "$f")"
        if [[ "$base" == *.exe ]]; then
            archive="${base%.exe}"
            (
                cd "$(dirname "$f")"
                # Ship as openjiuwen.exe inside the zip (Chrys-style).
                cp "$base" "${BINARY_BASENAME}.exe"
                pyapp_stage_usage_doc .
                zip -q "$release_dir/${archive}.zip" "${BINARY_BASENAME}.exe" "使用说明.md"
                rm -f "${BINARY_BASENAME}.exe" "使用说明.md"
            )
        else
            archive="$base"
            (
                cd "$(dirname "$f")"
                cp "$base" "$BINARY_BASENAME"
                pyapp_stage_usage_doc .
                tar -czf "$release_dir/${archive}.tar.gz" "$BINARY_BASENAME" "使用说明.md"
                rm -f "$BINARY_BASENAME" "使用说明.md"
            )
        fi
    done
    shopt -u nullglob

    # Include the wheel for pip users.
    local wheel
    wheel="$(pyapp_resolve_wheel "$version")"
    cp "$wheel" "$release_dir/"

    (
        cd "$release_dir"
        if command -v sha256sum >/dev/null 2>&1; then
            sha256sum -- * > SHA256SUMS.txt.tmp
        elif command -v shasum >/dev/null 2>&1; then
            shasum -a 256 -- * > SHA256SUMS.txt.tmp
        else
            return 0
        fi
        # Drop self-hash / tmp lines if present.
        grep -v -E '(^|[[:space:]])SHA256SUMS\.txt(\.tmp)?$' SHA256SUMS.txt.tmp > SHA256SUMS.txt \
            || mv SHA256SUMS.txt.tmp SHA256SUMS.txt
        rm -f SHA256SUMS.txt.tmp
        ls -la
        echo "---- SHA256SUMS ----" && cat SHA256SUMS.txt
    )
}

select_targets
[[ ${#SELECTED[@]} -gt 0 ]] || pyapp_die "no targets selected"

pyapp_require_cmd curl perl
pyapp_log "Building wheel once for all targets..."
pyapp_build_wheel

BUILT=()
SKIPPED=()

for t in "${SELECTED[@]}"; do
    plat="$(target_platform "$t")"
    echo
    pyapp_log "── Target $t ($plat) ──"

    if [[ "$plat" == "linux" && "$USE_DOCKER" == "true" ]]; then
        if ! command -v docker >/dev/null 2>&1; then
            echo "Skip $t: docker not available (pass --no-docker to force native)"
            SKIPPED+=("$t (no docker)")
            continue
        fi
        if build_linux_docker "$t"; then
            BUILT+=("$t")
        else
            SKIPPED+=("$t (docker build failed)")
        fi
        continue
    fi

    if pyapp_host_can_build_target "$t"; then
        if build_native "$t"; then
            BUILT+=("$t")
        else
            SKIPPED+=("$t (native build failed)")
        fi
    else
        echo "Skip $t: need a ${plat} host (or CI runner); Docker cannot replace ${plat} SDKs"
        SKIPPED+=("$t (wrong host OS)")
    fi
done

echo
pyapp_log "Built: ${BUILT[*]:-none}"
pyapp_log "Skipped: ${SKIPPED[*]:-none}"

if [[ "$DO_PACKAGE" == "true" ]]; then
    package_releases
fi

if [[ ${#BUILT[@]} -eq 0 ]]; then
    pyapp_die "no binaries were built"
fi
