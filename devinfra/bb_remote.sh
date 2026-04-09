#!/usr/bin/env bash
# bb remote wrapper with sane defaults for this repo.
# See devinfra/docs/bb_remote_internals.md for how bb remote works.
set -euo pipefail

# Abort if the default branch has unpushed commits — bb remote would
# select the local HEAD as the base commit, which doesn't exist on the
# remote and causes the runner to fail during git fetch.
# Skip on detached HEAD (GHA) or when origin/HEAD doesn't exist.
current_branch=$(git symbolic-ref --short HEAD || true)
if [ -n "$current_branch" ]; then
  default_branch=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's|^origin/||' || true)
  default_branch=${default_branch:-devel}
  if [ "$current_branch" = "$default_branch" ]; then
    local_sha=$(git rev-parse "$default_branch" || true)
    remote_sha=$(git rev-parse "origin/$default_branch" || true)
    if [ -n "$local_sha" ] && [ -n "$remote_sha" ] && [ "$local_sha" != "$remote_sha" ]; then
      echo "bb-remote: aborting — $default_branch has unpushed commits (local $local_sha != origin $remote_sha)." >&2
      echo "bb-remote: push first or use a feature branch." >&2
      exit 1
    fi
  fi
fi

# Forward CI secrets to the BB runner.
# Secrets: single --remote_run_header with comma-separated K=V pairs
#   (not cached, not visible in BB UI).
# Non-secrets: --env (cached, visible).
# TODO: restructure push_ghcr to run locally instead of forwarding GHCR creds.
extra_args=()
secret_overrides=()
[ -n "${DOCKER_CLIENT_KEY:-}" ] && secret_overrides+=("DOCKER_CLIENT_KEY=${DOCKER_CLIENT_KEY}")
[ -n "${GHCR_TOKEN:-}" ] && secret_overrides+=("GHCR_TOKEN=${GHCR_TOKEN}")
[ -n "${GH_RELEASE_PAT:-}" ] && secret_overrides+=("GH_RELEASE_PAT=${GH_RELEASE_PAT}")
if [ ${#secret_overrides[@]} -gt 0 ]; then
  IFS=','
  extra_args+=("--remote_run_header=x-buildbuddy-platform.env-overrides=${secret_overrides[*]}")
  unset IFS
fi
[ -n "${DOCKER_CLIENT_KEY:-}" ] && extra_args+=("--env=DOCKER_HOST=${DOCKER_HOST:-}" "--env=DOCKER_TLS_VERIFY=${DOCKER_TLS_VERIFY:-1}")
[ -n "${GHCR_TOKEN:-}" ] && extra_args+=("--env=GHCR_USERNAME=${GHCR_USERNAME:-agentydragon}")

exec bb remote \
  --runner_exec_properties=EstimatedFreeDiskBytes=50000000000 \
  --runner_exec_properties=workload-isolation-type=firecracker \
  --runner_exec_properties=init-dockerd=true \
  ${extra_args[@]+"${extra_args[@]}"} \
  "$@" --config=rbe
