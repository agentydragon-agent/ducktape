#!/usr/bin/env bash
# Pre-commit hook (prepare-commit-msg stage): block amending already-pushed commits.
#
# Git invokes prepare-commit-msg with:
#   $1 = commit message file
#   $2 = source: "commit" (amend), "message" (-m), "merge", "squash", or empty
#   $3 = SHA (only for amend)
#
# When $2 = "commit", this is a --amend. We check if HEAD has been pushed to
# any remote tracking branch. If so, we abort to prevent history rewriting.
set -euo pipefail

# Only act on amend commits
if [[ "${2:-}" != "commit" ]]; then
  exit 0
fi

# Check if HEAD exists on any remote branch
if git branch -r --contains HEAD 2>/dev/null | grep -q .; then
  echo "ERROR: Refusing to amend a commit that has already been pushed." >&2
  echo "Create a new commit instead. See AGENTS.md: \"NEVER amend a commit that has already been pushed.\"" >&2
  exit 1
fi
