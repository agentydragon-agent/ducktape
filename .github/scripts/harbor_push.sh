#!/usr/bin/env bash
# harbor_push.sh <bazel_load_target> <local_tag> <remote_repo>
#
# Runs `bazel run <bazel_load_target>` to build the OCI image and load it
# into the local Docker daemon, then pushes with tags: GITHUB_SHA and
# BRANCH-YYYYMMDDHHMMSS-sha7. Updates :latest only if the image digest
# changed (detected via crane), avoiding spurious tag updates when inputs
# are unchanged.
# Skips entirely on pull_request builds.
#
# Environment variables (set automatically by GitHub Actions):
#   GITHUB_SHA          - full commit SHA
#   GITHUB_REF_NAME     - branch or tag name
#   GITHUB_EVENT_NAME   - event that triggered the workflow
set -euo pipefail

bazel_target="$1"
local_tag="$2"
remote_repo="$3"

if [[ "${GITHUB_EVENT_NAME:-}" == "pull_request" ]]; then
  echo "PR build — skipping push"
  exit 0
fi

bazel run "$bazel_target"

echo "$remote_repo: pushing"

BRANCH="${GITHUB_REF_NAME//\//-}"
TS="$(date -u +%Y%m%d%H%M%S)"
TAG="${BRANCH}-${TS}-${GITHUB_SHA:0:7}"

for tag in "$remote_repo:$GITHUB_SHA" "$remote_repo:$TAG"; do
  docker tag "$local_tag" "$tag"
  docker push --quiet "$tag"
done

# Update :latest only if image content changed (OCI digest comparison).
SHA_DIGEST=$(crane digest "$remote_repo:$GITHUB_SHA")
LATEST_DIGEST=$(crane digest "$remote_repo:latest" 2>/dev/null || echo "")
if [[ "$SHA_DIGEST" == "$LATEST_DIGEST" ]]; then
  echo "$remote_repo: :latest unchanged (same digest), skipping tag update"
else
  echo "$remote_repo: content changed, updating :latest"
  crane tag "$remote_repo:$GITHUB_SHA" latest
fi
