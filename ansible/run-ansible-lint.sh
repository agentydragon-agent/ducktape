#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export ANSIBLE_LINT_SKIP_VAULT=1

# Strip "ansible/" prefix from file paths if present
# Pre-commit passes paths like "ansible/roles/cli/tasks/main.yml"
# but ansible-lint (running from ansible/) needs "roles/cli/tasks/main.yml"
stripped_args=()
for arg in "$@"; do
    stripped_args+=("${arg#ansible/}")
done

# If no arguments, scan all ansible files (default behavior)
if [ ${#stripped_args[@]} -eq 0 ]; then
    ansible-lint --config-file ../.ansible-lint.yaml
else
    ansible-lint --config-file ../.ansible-lint.yaml "${stripped_args[@]}"
fi
