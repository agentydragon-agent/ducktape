#!/usr/bin/env bash
# Check if ansible/ directory changed
# Usage: check-ansible-changes.sh <event_name> <base_ref>
set -euo pipefail

event_name="$1"
base_ref="${2:-}"

# Determine git diff range based on event type
if [ "$event_name" = "pull_request" ]; then
  diff_range="origin/${base_ref}...HEAD"
else
  diff_range="HEAD~1 HEAD"
fi

# Check if ansible/ changed (default to true if git diff fails)
if git diff --name-only $diff_range 2>/dev/null | grep -q '^ansible/'; then
  echo "changed=true"
elif [ "${PIPESTATUS[0]}" -ne 0 ]; then
  # git diff failed (e.g., first commit) - run ansible-lint
  echo "changed=true"
else
  echo "changed=false"
fi
