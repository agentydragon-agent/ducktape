#!/usr/bin/env bash
# Compute affected Bazel targets using bazel-diff
#
# Outputs to $GITHUB_OUTPUT:
#   targets: space-separated list of affected targets, or "//..." for full build
#   has_changes: "true" or "false"
#   has_props: "true" if //props/... targets are affected
#   has_editor_agent: "true" if //editor_agent/... targets are affected
#   has_agent_server: "true" if //agent_server/... targets are affected
#   has_finance: "true" if //finance/... targets are affected
#   has_props_frontend: "true" if //props/frontend/... targets are affected
#
# Falls back to full build (//...) on any failure.
set -euo pipefail

# Check if affected targets intersect with a pattern using bazel query
# Args: $1 = pattern (e.g., "//props/..."), $2 = output var name (e.g., "has_props")
# Uses global TARGETS variable (space-separated list or "//...")
check_intersection() {
  local pattern=$1
  local varname=$2

  if [[ -z "${TARGETS:-}" ]]; then
    echo "${varname}=false" >>"$GITHUB_OUTPUT"
    return
  fi

  local result=""
  if [[ "$TARGETS" == "//..." ]]; then
    # Full build - check if pattern has any targets
    result=$(bazelisk query "$pattern" 2>/dev/null | head -1 || true)
  else
    # Check intersection of target set with pattern
    result=$(bazelisk query "set($TARGETS) intersect $pattern" 2>/dev/null | head -1 || true)
  fi

  if [[ -n "$result" ]]; then
    echo "${varname}=true" >>"$GITHUB_OUTPUT"
  else
    echo "${varname}=false" >>"$GITHUB_OUTPUT"
  fi
}

# Output targets and compute all intersection flags
# Args: $1 = targets (space-separated or "//..."), $2 = has_changes ("true" or "false")
output_results() {
  local targets=$1
  local has_changes=$2

  TARGETS="$targets"
  echo "targets=$targets" >>"$GITHUB_OUTPUT"
  echo "has_changes=$has_changes" >>"$GITHUB_OUTPUT"

  if [[ "$has_changes" == "true" ]]; then
    echo "Computing path intersections..."
    check_intersection "//props/..." "has_props"
    check_intersection "//editor_agent/..." "has_editor_agent"
    check_intersection "//agent_server/..." "has_agent_server"
    check_intersection "//finance/..." "has_finance"
    check_intersection "//props/frontend/..." "has_props_frontend"
  else
    # No changes - all intersections are false
    echo "has_props=false" >>"$GITHUB_OUTPUT"
    echo "has_editor_agent=false" >>"$GITHUB_OUTPUT"
    echo "has_agent_server=false" >>"$GITHUB_OUTPUT"
    echo "has_finance=false" >>"$GITHUB_OUTPUT"
    echo "has_props_frontend=false" >>"$GITHUB_OUTPUT"
  fi
}

# Full build on main/devel branches (only use diffs for PRs)
if [[ "$GITHUB_EVENT_NAME" != "pull_request" ]]; then
  echo "Push to ${GITHUB_REF_NAME} branch, running full build"
  output_results "//..." "true"
  exit 0
fi

BAZEL_DIFF_VERSION="12.1.1"
BAZEL_DIFF_JAR="/tmp/bazel-diff.jar"

# Download bazel-diff
echo "Downloading bazel-diff v${BAZEL_DIFF_VERSION}..."
if ! curl -fsSL -o "$BAZEL_DIFF_JAR" \
  "https://github.com/Tinder/bazel-diff/releases/download/${BAZEL_DIFF_VERSION}/bazel-diff_deploy.jar"; then
  echo "Failed to download bazel-diff, falling back to full build"
  output_results "//..." "true"
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
  output_results "//..." "true"
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
  output_results "//..." "true"
  exit 0
fi

# Generate hashes and compute diff
CURRENT_SHA=$(git rev-parse HEAD)

echo "Generating hashes for base commit $BASE_SHA..."
git checkout --quiet "$BASE_SHA"
if ! java -jar "$BAZEL_DIFF_JAR" generate-hashes -w "$GITHUB_WORKSPACE" -b bazelisk /tmp/base.json; then
  echo "Base hash generation failed, falling back to full build"
  git checkout --quiet "$CURRENT_SHA"
  output_results "//..." "true"
  exit 0
fi

echo "Generating hashes for head commit $CURRENT_SHA..."
git checkout --quiet "$CURRENT_SHA"
if ! java -jar "$BAZEL_DIFF_JAR" generate-hashes -w "$GITHUB_WORKSPACE" -b bazelisk /tmp/head.json; then
  echo "Head hash generation failed, falling back to full build"
  output_results "//..." "true"
  exit 0
fi

echo "Computing impacted targets..."
if ! java -jar "$BAZEL_DIFF_JAR" get-impacted-targets -sh /tmp/base.json -fh /tmp/head.json -o /tmp/targets.txt; then
  echo "Target diff failed, falling back to full build"
  output_results "//..." "true"
  exit 0
fi

if [[ ! -s /tmp/targets.txt ]]; then
  echo "No Bazel targets affected"
  output_results "" "false"
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
  output_results "$TARGETS" "true"
fi
