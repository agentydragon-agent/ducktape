#!/usr/bin/env bash
set -e

# Install collections if not already present
if [ ! -d "collections/ansible_collections/community" ]; then
    echo "Installing Ansible collections..." >&2
    ansible-galaxy collection install -r requirements.yaml -p collections --force
fi

# Run ansible-lint with collections path
ANSIBLE_LINT_SKIP_VAULT=1 ANSIBLE_COLLECTIONS_PATH=collections ansible-lint --config-file ../.ansible-lint.yaml "$@"
