#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY_URL="https://github.com/aminhaiqal/axelyn-forge.git"
readonly DEPLOY_BRANCH="agent/resume-tailoring-pipeline"
readonly DEPLOY_ROOT="/home/debian/apps/axelyn-forge-deploy"
readonly REPOSITORY="${DEPLOY_ROOT}/repository.git"
readonly RELEASES="${DEPLOY_ROOT}/releases"
readonly CURRENT_LINK="${DEPLOY_ROOT}/current"
readonly ENV_FILE="/home/debian/apps/axelyn-forge/.env"
readonly LEGACY_RELEASE="/home/debian/apps/axelyn-forge"
readonly CONNECTED_LOG_MESSAGE="Forge Discord bot connected as"

if [[ ! ${SSH_ORIGINAL_COMMAND:-} =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
    echo "Refusing invalid deployment command" >&2
    exit 64
fi
readonly COMMIT_SHA="${BASH_REMATCH[1]}"

mkdir -p "$DEPLOY_ROOT" "$RELEASES"
exec 9>"${DEPLOY_ROOT}/deploy.lock"
if ! flock -n 9; then
    echo "Another Axelyn Forge deployment is already running" >&2
    exit 75
fi

if [[ ! -s "$ENV_FILE" ]]; then
    echo "Forge environment file is missing or empty: $ENV_FILE" >&2
    exit 78
fi

if [[ ! -d "$REPOSITORY" ]]; then
    git init --bare "$REPOSITORY"
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

readonly COMPOSE_FILE="${RELEASE}/compose.yaml"
if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "Release does not contain compose.yaml: $COMMIT_SHA" >&2
    exit 66
fi

previous_release=""
if [[ -L "$CURRENT_LINK" ]]; then
    previous_release="$(readlink -f "$CURRENT_LINK")"
elif [[ -f "${LEGACY_RELEASE}/compose.yaml" ]]; then
    previous_release="$LEGACY_RELEASE"
fi
readonly PREVIOUS_RELEASE="$previous_release"

compose() {
    FORGE_ENV_FILE="$ENV_FILE" docker compose -f "$COMPOSE_FILE" "$@"
}

rollback() {
    if [[ -n "$PREVIOUS_RELEASE" && -f "${PREVIOUS_RELEASE}/compose.yaml" ]]; then
        echo "Rolling back to ${PREVIOUS_RELEASE}" >&2
        FORGE_ENV_FILE="$ENV_FILE" docker compose \
            -f "${PREVIOUS_RELEASE}/compose.yaml" \
            up -d --build --force-recreate --remove-orphans
    else
        echo "No previous release is available for rollback" >&2
    fi
}

compose config -q
compose build
readonly DEPLOY_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if ! compose up -d --force-recreate --remove-orphans; then
    rollback
    exit 1
fi

connected=false
for _ in $(seq 1 45); do
    container_id="$(compose ps -q forge-discord)"
    if [[ -n "$container_id" ]] && \
        [[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" == "true" ]] && \
        grep -Fq "$CONNECTED_LOG_MESSAGE" \
            < <(docker logs --since "$DEPLOY_STARTED_AT" "$container_id" 2>&1); then
        connected=true
        break
    fi
    sleep 2
done

if [[ "$connected" != "true" ]]; then
    echo "The replacement bot did not connect to Discord within 90 seconds" >&2
    compose ps >&2 || true
    compose logs --tail 100 --no-color forge-discord >&2 || true
    rollback
    exit 1
fi

ln -sfn "$RELEASE" "${CURRENT_LINK}.next"
mv -Tf "${CURRENT_LINK}.next" "$CURRENT_LINK"

compose ps
echo "Deployed Axelyn Forge commit ${COMMIT_SHA}"
