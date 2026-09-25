#!/usr/bin/env bash
# Create/update a GitHub release for a tag and upload local artifacts.
#
# Usage:
#   ./scripts/pyapp/publish-github-release.sh <version|vX.Y.Z> [artifact-dir]
#
# Env:
#   GH_TOKEN / GITHUB_TOKEN   Optional if `gh auth login` already works
#   GITHUB_REMOTE            Remote name to resolve owner/repo (default: github)
#   GITHUB_OWNER / GITHUB_REPO  Override owner/repo
#
# Example:
#   ./scripts/pyapp/publish-github-release.sh 0.1.21 dist/release

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

GITHUB_REMOTE="${GITHUB_REMOTE:-github}"

usage() {
    cat <<'EOF'
Usage: publish-github-release.sh <version|vX.Y.Z> [artifact-dir]

Creates a GitHub release for the tag (if missing) and uploads files from
artifact-dir (default: dist/release): archives, wheel, VSIX, SHA256SUMS,
使用说明.md.

Uses the GitHub CLI (`gh`). Auth via `gh auth login` or GH_TOKEN/GITHUB_TOKEN.
Owner/repo default from the `github` remote URL.
EOF
}

VERSION_ARG="${1:-}"
ARTIFACT_DIR="${2:-$PROJECT_ROOT/dist/release}"

[[ -n "$VERSION_ARG" ]] || { usage; exit 1; }
[[ "$VERSION_ARG" != "-h" && "$VERSION_ARG" != "--help" ]] || { usage; exit 0; }

if [[ "$VERSION_ARG" == v* ]]; then
    TAG="$VERSION_ARG"
    VERSION="${VERSION_ARG#v}"
else
    VERSION="$VERSION_ARG"
    TAG="v${VERSION}"
fi

pyapp_require_cmd gh git

[[ -d "$ARTIFACT_DIR" ]] || pyapp_die "artifact dir not found: $ARTIFACT_DIR"

parse_github_owner_repo() {
    local url
    url="$(git -C "$PROJECT_ROOT" remote get-url "$GITHUB_REMOTE" 2>/dev/null || true)"
    [[ -n "$url" ]] || return 1
    # git@github.com:Owner/repo.git  or  https://github.com/Owner/repo.git
    if [[ "$url" =~ github\.com[:/]+([^/]+)/([^/.]+)(\.git)?$ ]]; then
        echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
        return 0
    fi
    return 1
}

if [[ -z "${GITHUB_OWNER:-}" || -z "${GITHUB_REPO:-}" ]]; then
    parsed="$(parse_github_owner_repo)" \
        || pyapp_die "cannot parse owner/repo from remote '${GITHUB_REMOTE}'; set GITHUB_OWNER and GITHUB_REPO"
    read -r _owner _repo <<< "$parsed"
    GITHUB_OWNER="${GITHUB_OWNER:-$_owner}"
    GITHUB_REPO="${GITHUB_REPO:-$_repo}"
fi

REPO_SLUG="${GITHUB_OWNER}/${GITHUB_REPO}"
NOTES="$(cat <<EOF
iCode ${VERSION}

See \`使用说明.md\` in the assets for install / slim vs full package notes.

Includes:
- platform binaries (\`icode-*-v${VERSION}.tar.gz\`, optional \`-full-\`)
- Python wheel (\`openjiuwen_icode-*-py3-none-any.whl\`)
- VS Code extension (\`icode-${VERSION}.vsix\`)

Primary development happens on GitCode; this GitHub repo is a sync/publish mirror.
Artifacts built by \`scripts/pyapp/release.sh\`.
EOF
)"

shopt -s nullglob
files=(
    "$ARTIFACT_DIR"/${BINARY_BASENAME}-*.tar.gz
    "$ARTIFACT_DIR"/${BINARY_BASENAME}-*.zip
    "$ARTIFACT_DIR"/*.whl
    "$ARTIFACT_DIR"/icode-*.vsix
    "$ARTIFACT_DIR"/SHA256SUMS.txt
    "$ARTIFACT_DIR"/使用说明.md
)
shopt -u nullglob

[[ ${#files[@]} -gt 0 ]] || pyapp_die "no uploadable artifacts in $ARTIFACT_DIR"

pyapp_log "Publishing GitHub release ${TAG} → ${REPO_SLUG}"
pyapp_log "Artifacts from: $ARTIFACT_DIR"

if gh release view "$TAG" --repo "$REPO_SLUG" >/dev/null 2>&1; then
    pyapp_log "GitHub release ${TAG} already exists; uploading/replacing assets"
    gh release upload "$TAG" "${files[@]}" \
        --repo "$REPO_SLUG" \
        --clobber
else
    pyapp_log "Creating GitHub release ${TAG}"
    gh release create "$TAG" "${files[@]}" \
        --repo "$REPO_SLUG" \
        --title "icode ${VERSION}" \
        --notes "$NOTES"
fi

pyapp_log "GitHub release published:"
echo "    https://github.com/${REPO_SLUG}/releases/tag/${TAG}"
