#!/usr/bin/env bash
# Create/update a GitCode release for a tag and upload local artifacts.
#
# Usage:
#   ./scripts/pyapp/publish-gitcode-release.sh <version|vX.Y.Z> [artifact-dir]
#
# Env:
#   GITCODE_TOKEN   Personal access token (required)
#   GITCODE_OWNER   Override owner (default: parsed from origin)
#   GITCODE_REPO    Override repo  (default: parsed from origin)
#   GITCODE_API_BASE  Default https://api.gitcode.com/api/v5
#   GITCODE_TARGET_COMMITISH  Default: current HEAD sha (or main)
#
# Example:
#   GITCODE_TOKEN=... ./scripts/pyapp/publish-gitcode-release.sh 0.1.3 dist/release

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

GITCODE_API_BASE="${GITCODE_API_BASE:-https://api.gitcode.com/api/v5}"

usage() {
    cat <<'EOF'
Usage: publish-gitcode-release.sh <version|vX.Y.Z> [artifact-dir]

Creates a GitCode release for the tag (if missing) and uploads files from
artifact-dir (default: dist/release): archives, wheel, VSIX, SHA256SUMS,
使用说明.md.

Requires GITCODE_TOKEN. Owner/repo default from `git remote get-url origin`.
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

pyapp_require_cmd curl jq git

if [[ -z "${GITCODE_TOKEN:-}" ]]; then
    pyapp_die "GITCODE_TOKEN is unset (create a GitCode personal access token with repo release scope)"
fi

[[ -d "$ARTIFACT_DIR" ]] || pyapp_die "artifact dir not found: $ARTIFACT_DIR"

parse_gitcode_owner_repo() {
    local url owner repo
    url="$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null || true)"
    [[ -n "$url" ]] || return 1
    # git@gitcode.com:owner/repo.git  or  https://gitcode.com/owner/repo.git
    if [[ "$url" =~ gitcode\.com[:/]+([^/]+)/([^/.]+)(\.git)?$ ]]; then
        owner="${BASH_REMATCH[1]}"
        repo="${BASH_REMATCH[2]}"
        echo "$owner $repo"
        return 0
    fi
    return 1
}

if [[ -z "${GITCODE_OWNER:-}" || -z "${GITCODE_REPO:-}" ]]; then
    parsed="$(parse_gitcode_owner_repo)" \
        || pyapp_die "cannot parse owner/repo from origin; set GITCODE_OWNER and GITCODE_REPO"
    read -r _owner _repo <<< "$parsed"
    GITCODE_OWNER="${GITCODE_OWNER:-$_owner}"
    GITCODE_REPO="${GITCODE_REPO:-$_repo}"
fi

TARGET_COMMITISH="${GITCODE_TARGET_COMMITISH:-}"
if [[ -z "$TARGET_COMMITISH" ]]; then
    TARGET_COMMITISH="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/icode-gitcode-release.XXXXXX")"
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT

urlencode() {
    jq -nr --arg value "$1" '$value | @uri'
}

curl_config_value() {
    jq -Rr @json <<< "$1"
}

write_curl_config() {
    # Keep token out of `ps` argv.
    local path="$1"
    local config_file="$2"
    {
        printf 'url = %s\n' "$(curl_config_value "${GITCODE_API_BASE}${path}")"
        printf 'url-query = %s\n' "$(curl_config_value "access_token=${GITCODE_TOKEN}")"
    } > "$config_file"
    chmod 600 "$config_file"
}

api_get() {
    local path="$1"
    local out="$2"
    local cfg="$WORK_DIR/get.curlrc"
    write_curl_config "$path" "$cfg"
    curl --retry 3 --retry-all-errors -sS --config "$cfg" -o "$out" -w '%{http_code}'
}

api_post_json() {
    local path="$1"
    local json_file="$2"
    local out="$3"
    local cfg="$WORK_DIR/post.curlrc"
    write_curl_config "$path" "$cfg"
    curl --retry 3 --retry-all-errors -sS --config "$cfg" \
        -o "$out" -w '%{http_code}' \
        -X POST \
        -H 'Content-Type: application/json' \
        --data @"$json_file"
}

ensure_release() {
    local encoded_tag response status create_json
    encoded_tag="$(urlencode "$TAG")"
    response="$WORK_DIR/release-by-tag.json"
    status="$(api_get "/repos/${GITCODE_OWNER}/${GITCODE_REPO}/releases/tags/${encoded_tag}" "$response")"
    if [[ "$status" =~ ^2 ]]; then
        pyapp_log "GitCode release ${TAG} already exists; uploading assets into it"
        return 0
    fi

    create_json="$WORK_DIR/create-release.json"
    jq -n \
        --arg tag "$TAG" \
        --arg name "icode ${VERSION}" \
        --arg body "$(cat <<EOF
iCode ${VERSION}

See \`使用说明.md\` in the assets for install / slim vs full package notes.

Includes:
- platform binaries (\`icode-*-v${VERSION}.tar.gz\`, optional \`-full-\`)
- Python wheel (\`openjiuwen_icode-*-py3-none-any.whl\`)
- VS Code extension (\`icode-${VERSION}.vsix\`)

Artifacts built by \`scripts/pyapp/release.sh\`.
EOF
)" \
        --arg commitish "$TARGET_COMMITISH" \
        '{
            tag_name: $tag,
            name: $name,
            body: $body,
            target_commitish: $commitish,
            release_status: "latest"
        }' > "$create_json"

    response="$WORK_DIR/create-release-response.json"
    status="$(api_post_json "/repos/${GITCODE_OWNER}/${GITCODE_REPO}/releases" "$create_json" "$response")"
    if [[ "$status" =~ ^2 ]]; then
        pyapp_log "Created GitCode release ${TAG}"
        return 0
    fi
    if jq -e '
        .error_code == 409
        or ((.error_message // .message // "") | tostring | test("already exists"; "i"))
    ' "$response" >/dev/null 2>&1; then
        pyapp_log "GitCode release ${TAG} already exists; reusing it"
        return 0
    fi
    echo "GitCode create-release response (HTTP ${status}):" >&2
    cat "$response" >&2 || true
    pyapp_die "failed to create GitCode release ${TAG}"
}

list_existing_assets() {
    local encoded_tag response status
    encoded_tag="$(urlencode "$TAG")"
    response="$WORK_DIR/release-current.json"
    status="$(api_get "/repos/${GITCODE_OWNER}/${GITCODE_REPO}/releases/tags/${encoded_tag}" "$response")"
    if [[ ! "$status" =~ ^2 ]]; then
        : > "$WORK_DIR/existing-assets.txt"
        return 0
    fi
    jq -r '.assets[]?.name // empty' "$response" | sort -u > "$WORK_DIR/existing-assets.txt"
}

upload_asset() {
    local file="$1"
    local filename encoded_filename encoded_tag
    local upload_json response_body request_config
    local upload_url_status http_status
    local upload_url x_obs_meta_project_id x_obs_acl x_obs_callback x_obs_content_type

    filename="$(basename "$file")"
    if grep -Fxq "$filename" "$WORK_DIR/existing-assets.txt" 2>/dev/null; then
        pyapp_log "Skip existing asset: $filename"
        return 0
    fi

    pyapp_log "Uploading $filename ..."
    encoded_filename="$(urlencode "$filename")"
    encoded_tag="$(urlencode "$TAG")"
    upload_json="$WORK_DIR/upload-url-${filename}.json"
    response_body="$WORK_DIR/upload-${filename}.response"
    request_config="$WORK_DIR/upload-url-${filename}.curlrc"

    write_curl_config \
        "/repos/${GITCODE_OWNER}/${GITCODE_REPO}/releases/${encoded_tag}/upload_url?file_name=${encoded_filename}" \
        "$request_config"

    upload_url_status="$(
        curl --retry 3 --retry-all-errors -sS \
            --config "$request_config" \
            -o "$upload_json" \
            -w '%{http_code}'
    )"
    if [[ ! "$upload_url_status" =~ ^2 ]]; then
        echo "upload_url response (HTTP ${upload_url_status}):" >&2
        cat "$upload_json" >&2 || true
        pyapp_die "failed to get upload URL for $filename"
    fi

    IFS=$'\t' read -r upload_url x_obs_meta_project_id x_obs_acl x_obs_callback x_obs_content_type < <(
        jq -r '[
            .url,
            (.headers["x-obs-meta-project-id"] // ""),
            (.headers["x-obs-acl"] // ""),
            (.headers["x-obs-callback"] // ""),
            (.headers["Content-Type"] // "application/octet-stream")
        ] | @tsv' "$upload_json"
    )

    [[ -n "$upload_url" ]] || pyapp_die "empty upload URL for $filename"

    http_status="$(
        curl --retry 3 --retry-all-errors -sS \
            -o "$response_body" \
            -w '%{http_code}' \
            -X PUT \
            -H "x-obs-meta-project-id: ${x_obs_meta_project_id}" \
            -H "x-obs-acl: ${x_obs_acl}" \
            -H "x-obs-callback: ${x_obs_callback}" \
            -H "Content-Type: ${x_obs_content_type}" \
            --upload-file "$file" \
            "$upload_url"
    )"
    if [[ ! "$http_status" =~ ^2 ]]; then
        echo "upload response (HTTP ${http_status}):" >&2
        cat "$response_body" >&2 || true
        pyapp_die "failed to upload $filename"
    fi
    echo "$filename" >> "$WORK_DIR/existing-assets.txt"
}

pyapp_log "Publishing GitCode release ${TAG} → ${GITCODE_OWNER}/${GITCODE_REPO}"
pyapp_log "Artifacts from: $ARTIFACT_DIR"
ensure_release
list_existing_assets

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

for f in "${files[@]}"; do
    [[ -f "$f" ]] || continue
    upload_asset "$f"
done

pyapp_log "GitCode release published:"
echo "    https://gitcode.com/${GITCODE_OWNER}/${GITCODE_REPO}/releases/${TAG}"
