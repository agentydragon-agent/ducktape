#!/usr/bin/env bash
set -e

# Bootstrap galaxy dependencies into the user cache before linting. This keeps
# the repo clean (nothing under version control) while ensuring CI/dev
# environments behave the same way.
echo "ansible-lint: installing role/collection requirements..." >&2
ROLE_PATH="${HOME}/.ansible/roles"
COLL_PATH="${HOME}/.ansible/collections"
mkdir -p "$ROLE_PATH" "$COLL_PATH"
ansible-galaxy role install -p "$ROLE_PATH" -r requirements.yaml >/dev/null 2>&1 || true
ansible-galaxy collection install -p "$COLL_PATH" -r requirements.yaml >/dev/null 2>&1 || true

# Run ansible-lint using the user cache (`~/.ansible/...`) plus repo-local roles.
# We set the env vars explicitly because ansible-lint spawns its own Python env
# and doesn’t always respect ansible.cfg search paths the way ansible-playbook
# does. This keeps lint results identical to full playbook runs.
export ANSIBLE_LINT_SKIP_VAULT=1
export ANSIBLE_COLLECTIONS_PATH="${ANSIBLE_COLLECTIONS_PATH:-$COLL_PATH:./collections}"
export ANSIBLE_ROLES_PATH="${ANSIBLE_ROLES_PATH:-$ROLE_PATH:./roles}"
ansible-lint --config-file ../.ansible-lint.yaml "$@"
