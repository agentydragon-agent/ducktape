#!/usr/bin/env bash
# In CI/ansible-lint environments, return mock password to allow syntax checks
# without vault access (Ansible requires non-empty password even for syntax checks)
if [ -n "$ANSIBLE_LINT_SKIP_VAULT" ]; then
  echo "mock_password_for_ci_syntax_check"
  exit 0
fi
exec secret-tool lookup service ansible-vault account ducktape
