#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CACHE_DIR="${SCRIPT_DIR}/.ansible"
ROLE_PATH="${CACHE_DIR}/roles"
COLL_PATH="${CACHE_DIR}/collections"

# Bootstrap galaxy dependencies into a repo-local cache before linting.
echo "ansible-lint: installing role/collection requirements..." >&2
mkdir -p "$ROLE_PATH" "$COLL_PATH"
ansible-galaxy role install -p "$ROLE_PATH" -r requirements.yaml >/dev/null 2>&1 || true
ansible-galaxy collection install -p "$COLL_PATH" -r requirements.yaml >/dev/null 2>&1 || true

export ANSIBLE_LINT_SKIP_VAULT=1
DEFAULT_COLLECTIONS_PATH="${COLL_PATH}:${SCRIPT_DIR}/collections"
if [[ -n "${ANSIBLE_COLLECTIONS_PATH:-}" ]]; then
  export ANSIBLE_COLLECTIONS_PATH="${DEFAULT_COLLECTIONS_PATH}:${ANSIBLE_COLLECTIONS_PATH}"
else
  export ANSIBLE_COLLECTIONS_PATH="${DEFAULT_COLLECTIONS_PATH}"
fi

DEFAULT_ROLES_PATH="${ROLE_PATH}:${SCRIPT_DIR}/roles"
if [[ -n "${ANSIBLE_ROLES_PATH:-}" ]]; then
  export ANSIBLE_ROLES_PATH="${DEFAULT_ROLES_PATH}:${ANSIBLE_ROLES_PATH}"
else
  export ANSIBLE_ROLES_PATH="${DEFAULT_ROLES_PATH}"
fi

ansible-lint --config-file ../.ansible-lint.yaml "$@"
