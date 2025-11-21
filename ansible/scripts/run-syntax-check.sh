#!/usr/bin/env bash
# Fast syntax check for Ansible files in pre-commit
# Only runs ansible-playbook --syntax-check on playbooks (much faster than ansible-lint)
# Full ansible-lint validation happens in CI

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Change to ansible directory (parent of scripts)
cd "$SCRIPT_DIR/.."

# Export SKIP_VAULT to avoid password prompts
export ANSIBLE_LINT_SKIP_VAULT=1

# Strip "ansible/" prefix from file paths if present
# Pre-commit passes paths like "ansible/roles/cli/tasks/main.yml"
# but we need "roles/cli/tasks/main.yml"
files=()
for arg in "$@"; do
    stripped="${arg#ansible/}"
    files+=("$stripped")
done

# If no arguments, check all playbooks
if [ ${#files[@]} -eq 0 ]; then
    # Find all playbooks (*.yaml files at root, excluding galaxy.yaml)
    mapfile -t playbooks < <(find . -maxdepth 1 -name "*.yaml" -type f ! -name "galaxy.yaml")

    if [ ${#playbooks[@]} -eq 0 ]; then
        echo "No playbooks found to syntax check"
        exit 0
    fi

    # Syntax check all playbooks
    for playbook in "${playbooks[@]}"; do
        echo "Syntax checking: $playbook"
        ansible-playbook --syntax-check "$playbook"
    done
    exit 0
fi

# Group files by type
playbooks=()
other_files=()

for file in "${files[@]}"; do
    # Check if it's a playbook (*.yaml at root level, not in subdirs)
    if [[ "$file" =~ ^[^/]+\.yaml$ ]] && [[ "$file" != "galaxy.yaml" ]]; then
        playbooks+=("$file")
    else
        # Role files, vars, etc. - skip syntax check (yamllint will catch YAML issues)
        other_files+=("$file")
    fi
done

# Syntax check playbooks
exit_code=0
for playbook in "${playbooks[@]}"; do
    echo "Syntax checking: $playbook"
    if ! ansible-playbook --syntax-check "$playbook"; then
        exit_code=1
    fi
done

# For non-playbook files, just note them (yamllint already handles these)
if [ ${#other_files[@]} -gt 0 ]; then
    echo "Note: Non-playbook files (${#other_files[@]} files) validated by yamllint hook"
fi

exit $exit_code
