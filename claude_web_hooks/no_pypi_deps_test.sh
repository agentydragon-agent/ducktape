#!/bin/bash
# Verifies that //claude_web_hooks has no @pypi// dependencies.
# This package runs before pip install in session hooks, so it must be self-contained.
set -euo pipefail

# Query all dependencies of the claude_web_hooks target
deps=$(bazelisk query 'deps(//claude_web_hooks:claude_web_hooks)' 2>/dev/null)

# Check for any @pypi// dependencies
pypi_deps=$(echo "$deps" | grep -E '^@pypi//' || true)

if [[ -n "$pypi_deps" ]]; then
  echo "ERROR: claude_web_hooks has external @pypi// dependencies!"
  echo "This package must be self-contained (no pip dependencies) because it runs"
  echo "before package installation in Claude Code session hooks."
  echo ""
  echo "Found dependencies:"
  echo "$pypi_deps"
  exit 1
fi

echo "OK: claude_web_hooks has no @pypi// dependencies"
