#!/usr/bin/env bash
# Prepare an iCode release:
#   1. Optionally bump / set the project version (CLI + VS Code extension);
#      commit if it changed
#   2. Tag HEAD as vX.Y.Z and push the commit + tag to origin
#   3. Build macOS + Linux PyApp binaries + vscode-icode .vsix into dist/release
#   4. Optionally publish artifacts to a GitCode release
#
# Usage:
#   ./scripts/pyapp/release.sh                  # bump patch, commit, tag, push, build
#   ./scripts/pyapp/release.sh --no-bump        # keep pyproject version; still tag/push HEAD
#   ./scripts/pyapp/release.sh --version 0.2.0  # set exact version
#   ./scripts/pyapp/release.sh --bump minor
#   ./scripts/pyapp/release.sh --bump major --uv --package-only
#
# Version options (mutually exclusive intent; last wins if mixed):
#   --bump patch|minor|major   Auto-increment (default: patch when bumping)
#   --version X.Y.Z            Set exact version
#   --no-bump                  Do not change version (alias: --keep-version)
#
# Build options:
#   --uv                 Pass --uv to slim PyApp builds
#   --full               Also build full-deps offline binaries (*-full-*)
#   --no-docker          Linux builds without Docker (native Linux + musl only)
#   --skip-build         Version bump/commit/tag/push only
#   --out-dir DIR        Release output dir (default: dist/release)
#   --dry-run            Print planned version/actions; do not write or build
#   --no-tag             Do not create a git tag
#   --no-push            Do not push commit/tag to origin
#   --force-tag          Move an existing tag onto HEAD if it points elsewhere
#   --publish            Upload artifacts to a GitCode release (non-interactive yes)
#   --no-publish         Skip GitCode release upload (non-interactive no)
#
#   ./scripts/pyapp/release.sh --no-bump --full
#
# After a successful build, asks whether to publish artifacts to GitCode unless
# --publish / --no-publish is set. Requires GITCODE_TOKEN for uploads.
#
# macOS binaries require a Darwin host; Linux targets use Docker when available.
# Windows is intentionally omitted (needs a Windows runner).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

VERSION_MODE="bump"       # bump | set | keep
BUMP_PART="patch"
SET_VERSION=""
USE_UV=false
USE_DOCKER=true
SKIP_BUILD=false
DRY_RUN=false
BUILD_FULL=false
DO_TAG=true
DO_PUSH=true
FORCE_TAG=false
PUBLISH_MODE="ask"   # ask | yes | no
OUT_DIR=""

usage() {
    cat <<'EOF'
Usage: release.sh [options]

Version:
  --bump patch|minor|major   Increment version (default action: patch)
  --version X.Y.Z            Set version explicitly
  --no-bump                  Keep current pyproject.toml version

Git:
  --no-tag                   Skip creating vX.Y.Z on HEAD
  --no-push                  Skip pushing commit/tag to origin
  --force-tag                Recreate tag on HEAD if it already exists elsewhere
  --publish                  Upload build artifacts to a GitCode release
  --no-publish               Do not upload to GitCode (skip the prompt)

Build:
  --uv                       Use uv installer in slim PyApp binaries
  --full                     Also build full-deps offline binaries (*-full-*)
  --no-docker                Do not use Docker for Linux targets
  --skip-build               Only handle version / commit / tag / push
  --out-dir DIR              Collect artifacts here (default: dist/release)
  --dry-run                  Show plan only

Examples:
  ./scripts/pyapp/release.sh
  ./scripts/pyapp/release.sh --no-bump
  ./scripts/pyapp/release.sh --no-bump --full
  ./scripts/pyapp/release.sh --version 0.2.0
  ./scripts/pyapp/release.sh --bump minor --out-dir dist/release-0.2.0
  GITCODE_TOKEN=... ./scripts/pyapp/release.sh --no-bump --full --publish
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bump)
            [[ $# -ge 2 ]] || pyapp_die "--bump requires patch|minor|major"
            VERSION_MODE="bump"
            BUMP_PART="$2"
            case "$BUMP_PART" in
                patch|minor|major) ;;
                *) pyapp_die "--bump must be patch, minor, or major" ;;
            esac
            shift 2
            ;;
        --version)
            [[ $# -ge 2 ]] || pyapp_die "--version requires X.Y.Z"
            VERSION_MODE="set"
            SET_VERSION="$2"
            shift 2
            ;;
        --no-bump|--keep-version)
            VERSION_MODE="keep"
            shift
            ;;
        --uv) USE_UV=true; shift ;;
        --full) BUILD_FULL=true; shift ;;
        --no-docker) USE_DOCKER=false; shift ;;
        --skip-build) SKIP_BUILD=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --no-tag) DO_TAG=false; shift ;;
        --no-push) DO_PUSH=false; shift ;;
        --force-tag) FORCE_TAG=true; shift ;;
        --publish) PUBLISH_MODE="yes"; shift ;;
        --no-publish) PUBLISH_MODE="no"; shift ;;
        --out-dir)
            [[ $# -ge 2 ]] || pyapp_die "--out-dir requires a path"
            OUT_DIR="$2"
            shift 2
            ;;
        -h|--help) usage; exit 0 ;;
        *) pyapp_die "unknown argument: $1 (see --help)" ;;
    esac
done

# Default when user passes neither --version nor --no-bump: bump patch.
# (VERSION_MODE already defaults to bump/patch.)

validate_semver() {
    [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] \
        || pyapp_die "invalid version '$1' (expected semver-like X.Y.Z)"
}

bump_semver() {
    local ver="$1" part="$2"
    local major minor patch rest
    if [[ "$ver" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(.*)$ ]]; then
        major="${BASH_REMATCH[1]}"
        minor="${BASH_REMATCH[2]}"
        patch="${BASH_REMATCH[3]}"
        rest="${BASH_REMATCH[4]}"
    else
        pyapp_die "cannot bump non-semver version: $ver"
    fi
    # Drop pre-release/build suffix on bump.
    rest=""
    case "$part" in
        major) major=$((major + 1)); minor=0; patch=0 ;;
        minor) minor=$((minor + 1)); patch=0 ;;
        patch) patch=$((patch + 1)) ;;
    esac
    echo "${major}.${minor}.${patch}${rest}"
}

read_pyproject_version() {
    (
        cd "$PROJECT_ROOT"
        python3 -c "
import tomllib, pathlib
print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])
"
    )
}

read_extension_version() {
    local pkg="$PROJECT_ROOT/extensions/vscode-icode/package.json"
    [[ -f "$pkg" ]] || { echo ""; return 0; }
    python3 -c "
import json, pathlib
print(json.loads(pathlib.Path(r'''$pkg''').read_text())['version'])
"
}

# Compare X.Y.Z semver tuples; print the greater one.
max_semver() {
    python3 -c "
import sys
def parse(v):
    parts = []
    for p in v.split('.'):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])
a, b = sys.argv[1], sys.argv[2]
print(a if parse(a) >= parse(b) else b)
" "$1" "$2"
}

write_version_files() {
    local new_version="$1"
    (
        cd "$PROJECT_ROOT"
        python3 - "$new_version" <<'PY'
import json
import pathlib
import re
import sys

new = sys.argv[1]
root = pathlib.Path(".")

pyproject = root / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
updated, n = re.subn(
    r'(?m)^(version\s*=\s*")[^"]*(")',
    rf'\g<1>{new}\2',
    text,
    count=1,
)
if n != 1:
    raise SystemExit("failed to update version in pyproject.toml")
pyproject.write_text(updated, encoding="utf-8")

cli_init = root / "openjiuwen_icode" / "__init__.py"
cli_text = cli_init.read_text(encoding="utf-8")
cli_updated, n = re.subn(
    r'(?m)^(__version__\s*=\s*")[^"]*(")',
    rf'\g<1>{new}\2',
    cli_text,
    count=1,
)
if n != 1:
    raise SystemExit("failed to update __version__ in openjiuwen_icode/__init__.py")
cli_init.write_text(cli_updated, encoding="utf-8")
print(f"updated pyproject.toml and openjiuwen_icode/__init__.py -> {new}", flush=True)

# Version-only bump of this editable package in uv.lock — do NOT run a
# full `uv lock` here: that re-fetches the whole graph from the configured
# index and fails the release when the mirror/network times out.
# (SDK package ``openjiuwen`` is a git dependency and is left alone.)
lock = root / "uv.lock"
if lock.is_file():
    lock_text = lock.read_text(encoding="utf-8")
    lock_updated, n = re.subn(
        r'(name = "openjiuwen-icode"\nversion = ")[^"]+("\nsource = \{ editable = "\." \})',
        rf'\g<1>{new}\2',
        lock_text,
        count=1,
    )
    if n != 1:
        raise SystemExit(
            "failed to update openjiuwen-icode version in uv.lock"
        )
    lock.write_text(lock_updated, encoding="utf-8")
    print(f"updated uv.lock openjiuwen-icode version -> {new}", flush=True)

# Keep VS Code extension on the same release version.
ext_pkg = root / "extensions" / "vscode-icode" / "package.json"
if ext_pkg.is_file():
    data = json.loads(ext_pkg.read_text(encoding="utf-8"))
    data["version"] = new
    ext_pkg.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"updated extensions/vscode-icode/package.json -> {new}", flush=True)

ext_lock = root / "extensions" / "vscode-icode" / "package-lock.json"
if ext_lock.is_file():
    lock_data = json.loads(ext_lock.read_text(encoding="utf-8"))
    lock_data["version"] = new
    root_pkg = lock_data.get("packages", {}).get("")
    if isinstance(root_pkg, dict):
        root_pkg["version"] = new
    ext_lock.write_text(
        json.dumps(lock_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"updated extensions/vscode-icode/package-lock.json -> {new}",
        flush=True,
    )
PY
    )
}

commit_version_bump() {
    local old_version="$1"
    local new_version="$2"
    (
        cd "$PROJECT_ROOT"
        pyapp_require_cmd git
        git add pyproject.toml openjiuwen_icode/__init__.py
        if [[ -f uv.lock ]]; then
            git add uv.lock
        fi
        if [[ -f extensions/vscode-icode/package.json ]]; then
            git add extensions/vscode-icode/package.json
        fi
        if [[ -f extensions/vscode-icode/package-lock.json ]]; then
            git add extensions/vscode-icode/package-lock.json
        fi
        if git diff --cached --quiet; then
            pyapp_log "No staged version changes to commit"
            return 0
        fi
        git commit -m "$(cat <<EOF
chore(release): bump icode ${old_version} -> ${new_version}

EOF
)"
        pyapp_log "Committed version bump ${old_version} -> ${new_version}"
    )
}

build_extension_vsix() {
    # Build extensions/vscode-icode → copy versioned .vsix into the release dir.
    local version="$1"
    local dest="$2"
    local ext_dir="$PROJECT_ROOT/extensions/vscode-icode"
    local vsix

    [[ -d "$ext_dir" ]] || {
        pyapp_log "No VS Code extension at $ext_dir; skipping"
        return 0
    }
    pyapp_require_cmd npm
    pyapp_log "Building VS Code extension (icode ${version})..."
    (
        cd "$ext_dir"
        npm install
        npm run package
    )
    shopt -s nullglob
    local candidates=("$ext_dir"/icode-"${version}".vsix "$ext_dir"/icode-*.vsix)
    shopt -u nullglob
    vsix=""
    for f in "${candidates[@]}"; do
        [[ -f "$f" ]] || continue
        if [[ "$(basename "$f")" == "icode-${version}.vsix" ]]; then
            vsix="$f"
            break
        fi
        vsix="$f"
    done
    [[ -n "$vsix" ]] || pyapp_die "extension package produced no .vsix under $ext_dir"
    mkdir -p "$dest"
    cp -f "$vsix" "$dest/icode-${version}.vsix"
    pyapp_log "Extension artifact: $dest/icode-${version}.vsix"
}

tag_and_push_release() {
    # Tag HEAD as vX.Y.Z (bump commit or current commit) and push to origin.
    local version="$1"
    local tag="v${version}"
    local head_sha remote_name existing

    (
        cd "$PROJECT_ROOT"
        pyapp_require_cmd git
        git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
            || pyapp_die "not a git repository"

        head_sha="$(git rev-parse HEAD)"
        remote_name="$(git remote 2>/dev/null | head -1 || true)"
        [[ -n "$remote_name" ]] || remote_name="origin"

        if [[ "$DO_TAG" == "true" ]]; then
            if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null 2>&1; then
                existing="$(git rev-parse "refs/tags/${tag}^{}")"
                if [[ "$existing" == "$head_sha" ]]; then
                    pyapp_log "Tag ${tag} already points at HEAD"
                elif [[ "$FORCE_TAG" == "true" ]]; then
                    pyapp_log "Moving tag ${tag} onto HEAD (--force-tag)"
                    git tag -f -a "$tag" -m "icode ${version}"
                else
                    pyapp_die \
                        "tag ${tag} already exists on ${existing:0:12} (HEAD ${head_sha:0:12}); pass --force-tag to move it"
                fi
            else
                git tag -a "$tag" -m "icode ${version}"
                pyapp_log "Created annotated tag ${tag} on ${head_sha:0:12}"
            fi
        else
            pyapp_log "Skipping git tag (--no-tag)"
        fi

        if [[ "$DO_PUSH" != "true" ]]; then
            pyapp_log "Skipping git push (--no-push)"
            return 0
        fi

        pyapp_log "Pushing HEAD to ${remote_name}..."
        git push -u "$remote_name" HEAD

        if [[ "$DO_TAG" == "true" ]]; then
            pyapp_log "Pushing tag ${tag} to ${remote_name}..."
            if [[ "$FORCE_TAG" == "true" ]]; then
                git push -f "$remote_name" "refs/tags/${tag}"
            else
                git push "$remote_name" "refs/tags/${tag}"
            fi
        fi
    )
}

maybe_publish_gitcode_release() {
    local version="$1"
    local artifact_dir="$2"
    local answer=""
    local tag="v${version}"

    case "$PUBLISH_MODE" in
        no)
            pyapp_log "Skipping GitCode release upload (--no-publish)"
            return 0
            ;;
        yes)
            answer="y"
            ;;
        ask)
            if [[ ! -t 0 ]]; then
                pyapp_log "Non-interactive stdin; skip GitCode publish (pass --publish to force)"
                return 0
            fi
            echo
            echo "Build artifacts are ready in: $artifact_dir"
            ls -la "$artifact_dir" || true
            echo
            read -r -p "Publish these files to GitCode as release ${tag}? [y/N] " answer
            ;;
        *)
            pyapp_die "internal error: unknown PUBLISH_MODE=$PUBLISH_MODE"
            ;;
    esac

    case "${answer}" in
        y|Y|yes|YES|Yes) ;;
        *)
            pyapp_log "Not publishing to GitCode"
            return 0
            ;;
    esac

    if [[ -z "${GITCODE_TOKEN:-}" ]]; then
        echo "GITCODE_TOKEN is not set." >&2
        echo "Create a personal access token on GitCode, then:" >&2
        echo "  export GITCODE_TOKEN=..." >&2
        echo "Re-run publish with:" >&2
        echo "  ./scripts/pyapp/publish-gitcode-release.sh ${version} ${artifact_dir}" >&2
        return 1
    fi

    "$SCRIPT_DIR/publish-gitcode-release.sh" "$version" "$artifact_dir"
}

collect_release_dir() {
    local version="$1"
    local dest="$2"
    local staged="$PROJECT_ROOT/dist/release"
    mkdir -p "$dest"

    local dest_real staged_real
    dest_real="$(cd "$dest" && pwd -P)"
    staged_real="$(cd "$staged" 2>/dev/null && pwd -P || true)"

    # Prefer freshly packaged archives from build-multi --package.
    # When --out-dir is the default dist/release, skip self-copy (macOS cp
    # errors with "are identical (not copied)" under set -e).
    if [[ -n "$staged_real" && "$staged_real" != "$dest_real" && -d "$staged" ]]; then
        shopt -s nullglob
        local f
        for f in "$staged"/*; do
            local base
            base="$(basename "$f")"
            case "$base" in
                *windows*) continue ;;
                SHA256SUMS.txt) continue ;;
                *) cp -f "$f" "$dest/" ;;
            esac
        done
        shopt -u nullglob
    fi

    # Also archive raw tagged binaries if archives were missing for a platform.
    shopt -s nullglob
    local bin
    for bin in "$PROJECT_ROOT/dist/${BINARY_BASENAME}-linux-"*-v"${version}" \
               "$PROJECT_ROOT/dist/${BINARY_BASENAME}-macos-"*-v"${version}"; do
        [[ -f "$bin" ]] || continue
        local name archive
        name="$(basename "$bin")"
        archive="$dest/${name}.tar.gz"
        if [[ ! -f "$archive" ]]; then
            (
                cd "$(dirname "$bin")"
                cp "$name" "$BINARY_BASENAME"
                pyapp_stage_usage_doc .
                tar -czf "$archive" "$BINARY_BASENAME" "使用说明.md"
                rm -f "$BINARY_BASENAME" "使用说明.md"
            )
        fi
    done
    shopt -u nullglob

    # Always ship the usage guide next to archives in the release directory.
    pyapp_stage_usage_doc "$dest"

    (
        cd "$dest"
        rm -f SHA256SUMS.txt
        if command -v sha256sum >/dev/null 2>&1; then
            sha256sum -- * > SHA256SUMS.txt 2>/dev/null || true
        elif command -v shasum >/dev/null 2>&1; then
            shasum -a 256 -- * > SHA256SUMS.txt 2>/dev/null || true
        fi
        if [[ -f SHA256SUMS.txt ]]; then
            grep -v -E '(^|[[:space:]])SHA256SUMS\.txt$' SHA256SUMS.txt > SHA256SUMS.txt.tmp \
                && mv SHA256SUMS.txt.tmp SHA256SUMS.txt \
                || rm -f SHA256SUMS.txt.tmp
        fi
    )

    pyapp_log "Release artifacts in $dest:"
    ls -la "$dest"
}

# ── Version planning ─────────────────────────────────────────────────
CLI_PKG_VERSION="$(read_pyproject_version)"
EXT_VERSION="$(read_extension_version)"
if [[ -n "$EXT_VERSION" ]]; then
    OLD_VERSION="$(max_semver "$CLI_PKG_VERSION" "$EXT_VERSION")"
else
    OLD_VERSION="$CLI_PKG_VERSION"
fi

case "$VERSION_MODE" in
    keep)
        NEW_VERSION="$CLI_PKG_VERSION"
        if [[ -n "$EXT_VERSION" && "$EXT_VERSION" != "$NEW_VERSION" ]]; then
            pyapp_die \
                "version mismatch under --no-bump: pyproject=${CLI_PKG_VERSION} extension=${EXT_VERSION}. Pass --version X.Y.Z (or bump) so CLI + VS Code extension share one release version."
        fi
        ;;
    set)
        validate_semver "$SET_VERSION"
        NEW_VERSION="$SET_VERSION"
        ;;
    bump)
        # Bump from the higher of CLI / extension so we never downgrade the VSIX.
        if [[ -n "$EXT_VERSION" && "$EXT_VERSION" != "$CLI_PKG_VERSION" ]]; then
            pyapp_log "Unifying versions from pyproject=${CLI_PKG_VERSION} extension=${EXT_VERSION} (base=${OLD_VERSION})"
        fi
        NEW_VERSION="$(bump_semver "$OLD_VERSION" "$BUMP_PART")"
        validate_semver "$NEW_VERSION"
        ;;
esac

if [[ -z "$OUT_DIR" ]]; then
    OUT_DIR="$PROJECT_ROOT/dist/release"
else
    # Absolute-ize relative paths against repo root.
    if [[ "$OUT_DIR" != /* ]]; then
        OUT_DIR="$PROJECT_ROOT/$OUT_DIR"
    fi
fi

pyapp_log "Current version: pyproject=${CLI_PKG_VERSION} extension=${EXT_VERSION:-n/a} (bump-base=${OLD_VERSION})"
pyapp_log "Release version: $NEW_VERSION"
pyapp_log "Output dir:      $OUT_DIR"
pyapp_log "Git tag/push:    tag=$([[ "$DO_TAG" == "true" ]] && echo v${NEW_VERSION} || echo skip) push=$([[ "$DO_PUSH" == "true" ]] && echo yes || echo no)"
pyapp_log "GitCode publish: $PUBLISH_MODE"
if [[ "$DRY_RUN" == "true" ]]; then
    pyapp_log "Dry run only — no writes, commit, tag, push, build, or publish"
    exit 0
fi

# ── Apply version + commit ───────────────────────────────────────────
CLI_VERSION="$(
    python3 -c "
import re, pathlib
t = pathlib.Path(r'''$PROJECT_ROOT/openjiuwen_icode/__init__.py''').read_text()
m = re.search(r'(?m)^__version__\s*=\s*\"([^\"]*)\"', t)
print(m.group(1) if m else '')
"
)"
EXT_NOW="$(read_extension_version)"

VERSION_CHANGED=false
need_write=false
if [[ "$NEW_VERSION" != "$CLI_PKG_VERSION" || "$CLI_VERSION" != "$NEW_VERSION" ]]; then
    need_write=true
fi
if [[ -n "$EXT_NOW" && "$EXT_NOW" != "$NEW_VERSION" ]]; then
    need_write=true
fi

if [[ "$need_write" == "true" ]]; then
    if [[ "$VERSION_MODE" == "keep" ]]; then
        echo "Warning: version files out of sync with ${NEW_VERSION}; not rewriting under --no-bump." >&2
    else
        VERSION_CHANGED=true
        write_version_files "$NEW_VERSION"
        commit_version_bump "$OLD_VERSION" "$NEW_VERSION"
    fi
else
    # Recover from an interrupted prior run: version files already match
    # NEW_VERSION on disk but were never committed.
    if git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
        && ! git -C "$PROJECT_ROOT" diff --quiet -- pyproject.toml \
            openjiuwen_icode/__init__.py uv.lock \
            extensions/vscode-icode/package.json \
            extensions/vscode-icode/package-lock.json 2>/dev/null; then
        HEAD_VER="$(
            git -C "$PROJECT_ROOT" show HEAD:pyproject.toml 2>/dev/null \
                | python3 -c "import sys,tomllib; print(tomllib.loads(sys.stdin.read())['project']['version'])" \
                || echo "$OLD_VERSION"
        )"
        if [[ "$HEAD_VER" != "$NEW_VERSION" ]]; then
            pyapp_log "Detected uncommitted version bump ${HEAD_VER} -> ${NEW_VERSION}; committing"
            VERSION_CHANGED=true
            write_version_files "$NEW_VERSION"
            commit_version_bump "$HEAD_VER" "$NEW_VERSION"
        else
            pyapp_log "Version unchanged; skipping commit"
        fi
    else
        pyapp_log "Version unchanged; skipping commit"
    fi
fi

# Tag the bump commit (or current HEAD with --no-bump) and push to remote
# before the long binary build, so the release ref exists even if packaging fails.
tag_and_push_release "$NEW_VERSION"

if [[ "$SKIP_BUILD" == "true" ]]; then
    pyapp_log "Skipping binary build (--skip-build)"
    pyapp_log "Release ref ready: v${NEW_VERSION}"
    exit 0
fi

# ── Build macOS + Linux (single pass so --package does not wipe peers) ─
pyapp_require_cmd curl perl cargo
RELEASE_TARGETS="x86_64-unknown-linux-musl,aarch64-unknown-linux-musl,aarch64-apple-darwin,x86_64-apple-darwin"
BUILD_ARGS=(--package --targets "$RELEASE_TARGETS")
[[ "$USE_UV" == "true" ]] && BUILD_ARGS+=(--uv)
[[ "$BUILD_FULL" == "true" ]] && BUILD_ARGS+=(--full)
[[ "$USE_DOCKER" != "true" ]] && BUILD_ARGS+=(--no-docker)

# Export so nested builds stamp the intended version even if env was set.
export PROJECT_VERSION="$NEW_VERSION"

echo
if [[ "$BUILD_FULL" == "true" ]]; then
    pyapp_log "Building Linux + macOS binaries (slim + full)..."
else
    pyapp_log "Building Linux + macOS binaries (slim only; pass --full for offline bundles)..."
fi
set +e
"$SCRIPT_DIR/build-multi.sh" "${BUILD_ARGS[@]}"
build_rc=$?
set -e
if [[ "$build_rc" -ne 0 ]]; then
    echo "Warning: build-multi.sh exited ${build_rc}; collecting whatever artifacts exist..." >&2
fi

# build-multi packages into dist/release; gather/normalize into OUT_DIR.
if [[ "$OUT_DIR" != "$PROJECT_ROOT/dist/release" ]]; then
    mkdir -p "$OUT_DIR"
    if [[ -d "$PROJECT_ROOT/dist/release" ]]; then
        shopt -s nullglob
        for f in "$PROJECT_ROOT/dist/release"/*; do
            cp -f "$f" "$OUT_DIR/"
        done
        shopt -u nullglob
    fi
fi

collect_release_dir "$NEW_VERSION" "$OUT_DIR"

# VS Code extension shares the same version; package .vsix into the release dir.
build_extension_vsix "$NEW_VERSION" "$OUT_DIR"

# Refresh checksums after adding the VSIX.
(
    cd "$OUT_DIR"
    rm -f SHA256SUMS.txt
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -- * > SHA256SUMS.txt 2>/dev/null || true
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 -- * > SHA256SUMS.txt 2>/dev/null || true
    fi
    if [[ -f SHA256SUMS.txt ]]; then
        grep -v -E '(^|[[:space:]])SHA256SUMS\.txt$' SHA256SUMS.txt > SHA256SUMS.txt.tmp \
            && mv SHA256SUMS.txt.tmp SHA256SUMS.txt \
            || rm -f SHA256SUMS.txt.tmp
    fi
)

# Fail if nothing useful was produced.
shopt -s nullglob
ARTIFACTS=(
    "$OUT_DIR"/${BINARY_BASENAME}-linux-*
    "$OUT_DIR"/${BINARY_BASENAME}-macos-*
    "$OUT_DIR"/*.whl
    "$OUT_DIR"/icode-*.vsix
)
shopt -u nullglob
if [[ ${#ARTIFACTS[@]} -eq 0 ]]; then
    pyapp_die "no macOS/Linux/extension release artifacts found in $OUT_DIR"
fi

pyapp_log "Release ready: v${NEW_VERSION}"
if [[ "$VERSION_CHANGED" == "true" ]]; then
    echo "    Version commit created and pushed (with tag when enabled)."
elif [[ "$DO_TAG" == "true" ]]; then
    echo "    Tagged HEAD as v${NEW_VERSION} (pushed when enabled)."
fi
echo "    Artifacts: $OUT_DIR"

# Interactive (or --publish / --no-publish) GitCode release upload.
set +e
maybe_publish_gitcode_release "$NEW_VERSION" "$OUT_DIR"
publish_rc=$?
set -e
if [[ "$publish_rc" -ne 0 ]]; then
    echo "Warning: GitCode publish failed (exit ${publish_rc}); local artifacts remain in $OUT_DIR" >&2
    exit "$publish_rc"
fi
