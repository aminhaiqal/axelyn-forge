#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY_URL="https://github.com/aminhaiqal/axelyn-forge.git"
readonly DEPLOY_BRANCH="main"
readonly DEPLOY_ROOT="/home/debian/apps/axelyn-forge-site"
readonly REPOSITORY="${DEPLOY_ROOT}/repository.git"
readonly RELEASES="${DEPLOY_ROOT}/releases"
readonly CURRENT_LINK="${DEPLOY_ROOT}/current"
readonly ENV_FILE="${DEPLOY_ROOT}/.env"
readonly PROJECT_NAME="axelyn-forge"

if [[ ! ${SSH_ORIGINAL_COMMAND:-} =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
    echo "Refusing invalid deployment command" >&2
    exit 64
fi
readonly COMMIT_SHA="${BASH_REMATCH[1]}"
readonly IMAGE_TAG="sha-${COMMIT_SHA:0:7}"

mkdir -p "$DEPLOY_ROOT" "$RELEASES"
exec 9>"${DEPLOY_ROOT}/deploy.lock"
if ! flock -n 9; then
    echo "Another Axelyn Forge production deployment is already running" >&2
    exit 75
fi

if [[ ! -s "$ENV_FILE" ]]; then
    echo "Forge production environment file is missing or empty: $ENV_FILE" >&2
    exit 78
fi

if [[ ! -d "$REPOSITORY" ]]; then
    git init --bare "$REPOSITORY" >/dev/null
    git --git-dir="$REPOSITORY" remote add origin "$REPOSITORY_URL"
fi

git --git-dir="$REPOSITORY" fetch --quiet --prune origin \
    "+refs/heads/${DEPLOY_BRANCH}:refs/remotes/origin/${DEPLOY_BRANCH}"
readonly BRANCH_HEAD="$(
    git --git-dir="$REPOSITORY" rev-parse "refs/remotes/origin/${DEPLOY_BRANCH}"
)"
if [[ "$COMMIT_SHA" != "$BRANCH_HEAD" ]]; then
    echo "Refusing stale or non-production commit: $COMMIT_SHA" >&2
    exit 65
fi
git --git-dir="$REPOSITORY" cat-file -e "${COMMIT_SHA}^{commit}"

readonly RELEASE="${RELEASES}/${COMMIT_SHA}"
if [[ ! -d "$RELEASE" ]]; then
    readonly TEMP_RELEASE="${RELEASE}.incomplete"
    rm -rf -- "$TEMP_RELEASE"
    mkdir -p "$TEMP_RELEASE"
    git --git-dir="$REPOSITORY" archive "$COMMIT_SHA" | tar -x -C "$TEMP_RELEASE"
    printf '%s\n' "$COMMIT_SHA" > "${TEMP_RELEASE}/.forge-release"
    mv "$TEMP_RELEASE" "$RELEASE"
fi

readonly COMPOSE_FILE="${RELEASE}/infra/compose.production.yaml"
if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "Release does not contain infra/compose.production.yaml: $COMMIT_SHA" >&2
    exit 66
fi

previous_release=""
if [[ -L "$CURRENT_LINK" ]]; then
    previous_release="$(readlink -f "$CURRENT_LINK")"
fi
readonly PREVIOUS_RELEASE="$previous_release"

compose_release() {
    local release="$1"
    local commit="$2"
    shift 2
    local compose_file="${release}/infra/compose.production.yaml"
    local image_tag="sha-${commit:0:7}"
    FORGE_API_IMAGE="ghcr.io/aminhaiqal/axelyn-forge-api:${image_tag}" \
    FORGE_CONVERTER_IMAGE="ghcr.io/aminhaiqal/axelyn-forge-converter:${image_tag}" \
    FORGE_FRONTEND_IMAGE="ghcr.io/aminhaiqal/axelyn-forge-frontend:${image_tag}" \
    FORGE_WEB_IMAGE="ghcr.io/aminhaiqal/axelyn-forge-web:${image_tag}" \
        docker compose \
            --env-file "$ENV_FILE" \
            --project-name "$PROJECT_NAME" \
            --file "$compose_file" \
            "$@"
}

rollback() {
    if [[ -z "$PREVIOUS_RELEASE" || ! -f "${PREVIOUS_RELEASE}/infra/compose.production.yaml" ]]; then
        echo "No previous production release is available for rollback" >&2
        return
    fi
    local previous_commit
    if [[ -f "${PREVIOUS_RELEASE}/.forge-release" ]]; then
        previous_commit="$(cat "${PREVIOUS_RELEASE}/.forge-release")"
    else
        previous_commit="$(basename "$PREVIOUS_RELEASE")"
    fi
    echo "Rolling back to ${previous_commit}" >&2
    compose_release "$PREVIOUS_RELEASE" "$previous_commit" \
        up -d --force-recreate --remove-orphans --wait --wait-timeout 240
}

compose_release "$RELEASE" "$COMMIT_SHA" config --quiet
compose_release "$RELEASE" "$COMMIT_SHA" pull
if ! compose_release "$RELEASE" "$COMMIT_SHA" \
    up -d --force-recreate --remove-orphans --wait --wait-timeout 240; then
    rollback
    exit 1
fi

ln -sfn "$RELEASE" "${CURRENT_LINK}.next"
mv -Tf "${CURRENT_LINK}.next" "$CURRENT_LINK"

compose_release "$RELEASE" "$COMMIT_SHA" ps
echo "Deployed Axelyn Forge production commit ${COMMIT_SHA} (${IMAGE_TAG})"
