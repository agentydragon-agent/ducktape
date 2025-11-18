#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export ANSIBLE_LINT_SKIP_VAULT=1

ansible-lint --config-file ../.ansible-lint.yaml "$@"
