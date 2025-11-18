#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export ANSIBLE_LINT_SKIP_VAULT=1

# Strip 'ansible/' prefix from file paths if present (for pre-commit integration)
# This handles the case where we're called from repo root with paths like 'ansible/roles/...'
# but we're already cd'd into the ansible/ directory
args=()
for arg in "$@"; do
    # Remove leading 'ansible/' if present
    args+=("${arg#ansible/}")
done

ansible-lint --config-file ../.ansible-lint.yaml "${args[@]}"
