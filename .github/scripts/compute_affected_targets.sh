#!/usr/bin/env bash
# Compute affected Bazel targets using bazel-diff
#
# Outputs to $GITHUB_OUTPUT:
#   targets: space-separated list of affected targets, or "//..." for full build
#   has_changes: "true" or "false"
#
# Falls back to full build (//...) on any failure.
set -euo pipefail

# Full build on main/devel branches (only use diffs for PRs)
if [[ "$GITHUB_EVENT_NAME" != "pull_request" ]]; then
  echo "Push to ${GITHUB_REF_NAME} branch, running full build"
  echo "targets=//..." >>"$GITHUB_OUTPUT"
  echo "has_changes=true" >>"$GITHUB_OUTPUT"
  exit 0
fi

BAZEL_DIFF_VERSION="12.1.1"
BAZEL_DIFF_JAR="/tmp/bazel-diff.jar"

# Download bazel-diff
echo "Downloading bazel-diff v${BAZEL_DIFF_VERSION}..."
if ! curl -fsSL -o "$BAZEL_DIFF_JAR" \
  "https://github.com/Tinder/bazel-diff/releases/download/${BAZEL_DIFF_VERSION}/bazel-diff_deploy.jar"; then
  echo "Failed to download bazel-diff, falling back to full build"
  echo "targets=//..." >>"$GITHUB_OUTPUT"
  echo "has_changes=true" >>"$GITHUB_OUTPUT"
  exit 0
fi

# Determine base commit
if [[ "$GITHUB_EVENT_NAME" == "pull_request" ]]; then
  BASE_SHA=$(git merge-base "origin/$GITHUB_BASE_REF" HEAD)
  echo "Pull request: comparing against merge-base $BASE_SHA"
else
  BASE_SHA=$(git rev-parse HEAD~1 2>/dev/null || echo "")
  echo "Push: comparing against HEAD~1 ($BASE_SHA)"
fi

# Infrastructure patterns that require full build
INFRA_PATTERNS="^MODULE\.bazel$|^MODULE\.bazel\.lock$|^requirements_bazel\.txt$|^\.bazelrc$|^\.bazelversion$|^tools/|^WORKSPACE"

if [[ -z "$BASE_SHA" ]]; then
  echo "No base SHA (new branch or initial commit), running all targets"
  echo "targets=//..." >>"$GITHUB_OUTPUT"
  echo "has_changes=true" >>"$GITHUB_OUTPUT"
  exit 0
fi

changed_files=$(git diff --name-only "$BASE_SHA"...HEAD)
echo "Changed files:"
echo "$changed_files" | head -20
if [[ $(echo "$changed_files" | wc -l) -gt 20 ]]; then
  echo "... and more"
fi

if echo "$changed_files" | grep -qE "$INFRA_PATTERNS"; then
  echo "Infrastructure change detected, running all targets"
  echo "targets=//..." >>"$GITHUB_OUTPUT"
  echo "has_changes=true" >>"$GITHUB_OUTPUT"
  exit 0
fi

# Generate hashes and compute diff
CURRENT_SHA=$(git rev-parse HEAD)

echo "Generating hashes for base commit $BASE_SHA..."
git checkout --quiet "$BASE_SHA"
if ! java -jar "$BAZEL_DIFF_JAR" generate-hashes -w "$GITHUB_WORKSPACE" -b bazelisk /tmp/base.json; then
  echo "Base hash generation failed, falling back to full build"
  git checkout --quiet "$CURRENT_SHA"
  echo "targets=//..." >>"$GITHUB_OUTPUT"
  echo "has_changes=true" >>"$GITHUB_OUTPUT"
  exit 0
fi

echo "Generating hashes for head commit $CURRENT_SHA..."
git checkout --quiet "$CURRENT_SHA"
if ! java -jar "$BAZEL_DIFF_JAR" generate-hashes -w "$GITHUB_WORKSPACE" -b bazelisk /tmp/head.json; then
  echo "Head hash generation failed, falling back to full build"
  echo "targets=//..." >>"$GITHUB_OUTPUT"
  echo "has_changes=true" >>"$GITHUB_OUTPUT"
  exit 0
fi

echo "Computing impacted targets..."
if ! java -jar "$BAZEL_DIFF_JAR" get-impacted-targets -sh /tmp/base.json -fh /tmp/head.json -o /tmp/targets.txt; then
  echo "Target diff failed, falling back to full build"
  echo "targets=//..." >>"$GITHUB_OUTPUT"
  echo "has_changes=true" >>"$GITHUB_OUTPUT"
  exit 0
fi

if [[ ! -s /tmp/targets.txt ]]; then
  echo "No Bazel targets affected"
  echo "targets=" >>"$GITHUB_OUTPUT"
  echo "has_changes=false" >>"$GITHUB_OUTPUT"
else
  target_count=$(wc -l </tmp/targets.txt)
  echo "Found $target_count affected targets"
  if [[ $target_count -le 20 ]]; then
    cat /tmp/targets.txt
  else
    head -20 /tmp/targets.txt
    echo "... and $((target_count - 20)) more"
  fi
  TARGETS=$(tr '\n' ' ' </tmp/targets.txt)
  echo "targets=$TARGETS" >>"$GITHUB_OUTPUT"
  echo "has_changes=true" >>"$GITHUB_OUTPUT"
fi
