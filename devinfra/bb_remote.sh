#!/usr/bin/env bash
# bb remote wrapper with sane defaults for this repo.
# See devinfra/docs/bb_remote_internals.md for how bb remote works.
set -euo pipefail

# Abort if the default branch has unpushed commits — bb remote would
# select the local HEAD as the base commit, which doesn't exist on the
# remote and causes the runner to fail during git fetch.
default_branch=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
default_branch=${default_branch:-devel}
local_sha=$(git rev-parse "$default_branch" 2>/dev/null)
remote_sha=$(git rev-parse "origin/$default_branch" 2>/dev/null)
current_branch=$(git symbolic-ref --short HEAD 2>/dev/null)
if [ "$current_branch" = "$default_branch" ] && [ "$local_sha" != "$remote_sha" ]; then
  echo "bb-remote: aborting — $default_branch has unpushed commits (local $local_sha != origin $remote_sha)." >&2
  echo "bb-remote: push first or use a feature branch." >&2
  exit 1
fi

exec bb remote \
  --runner_exec_properties=EstimatedFreeDiskBytes=50000000000 \
  --runner_exec_properties=workload-isolation-type=firecracker \
  --runner_exec_properties=init-dockerd=true \
  "$@" --config=rbe
