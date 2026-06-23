#!/usr/bin/env bash
# haku-worker entrypoint (runs in haku-sandbox): clone Haku's home into the agent
# workdir, then long-poll Anthropic's self-hosted work queue with the fixed `ant`
# toolset. The pod holds ONLY the environment key (sk-ant-oat01-...), never the
# org-scoped API key — so a prompt-injected tool call can't reach the control plane.
set -euo pipefail

workspace=/workspace
ducktape_dir="$workspace/ducktape"
state_dir="$workspace/haku-state"

# git auth for the Forgejo host, off any command line.
umask 077
printf 'machine %s login %s password %s\n' \
  "$HAKU_GIT_HOST" "$HAKU_GIT_USERNAME" "$HAKU_GIT_PASSWORD" >"$HOME/.netrc"

clone_or_pull() { # <url> <dest> [extra git clone flags...]
  if [ -d "$2/.git" ]; then
    git -C "$2" pull --ff-only
  else
    git clone "${@:3}" "$1" "$2"
  fi
}

# Behavior: ducktape's haku/base + haku/run.md, read at runtime (live-editable —
# no image rebuild to change the manual). NOT --depth 1: the run procedure's
# base-sync diffs HEAD against the last-reconciled commit (`git log <pin>..HEAD`),
# which needs that commit present. A week of history covers the wake cadence;
# a `git log` that reaches past the pin just errors empty (and an empty tool
# result currently deadlocks the session — ant posts "" and the API 400s it).
clone_or_pull "$HAKU_DUCKTAPE_REPO_URL" "$ducktape_dir" --shallow-since="1 week ago"
# Memory + the only write surface.
clone_or_pull "$HAKU_STATE_REPO_URL" "$state_dir" --depth 1
git -C "$state_dir" config user.name haku
git -C "$state_dir" config user.email haku@allegedly.works

# kubectl uses the pod's haku ServiceAccount token automatically (in-cluster);
# no kubeconfig to materialize, unlike the Claude Code web home.
#
# ANT_DEBUG (set in the Deployment manifest) toggles ant's verbose logging: the
# global --debug flag must precede the subcommand. Empty/unset = off. Useful for
# diagnosing the worker's session-tool-runner stream (claim vs result-submission)
# — e.g. when sessions stall at "idle" behind the mitmproxy egress.
exec ant ${ANT_DEBUG:+--debug} beta:worker poll \
  --environment-id "$ANTHROPIC_ENVIRONMENT_ID" \
  --workdir "$workspace"
