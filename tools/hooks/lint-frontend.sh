#!/bin/bash
# Bazel lint hook for frontend files (ESLint/Prettier).
# Runs when JS/TS/Svelte files in props/frontend are changed.

set -e

[ $# -eq 0 ] && exit 0

# Check if any files are in props/frontend
FRONTEND_FILES=$(printf '%s\n' "$@" | grep -E '^props/frontend/.*\.(ts|js|svelte)$' || true)
[ -z "$FRONTEND_FILES" ] && exit 0

echo "Running frontend linters (ESLint + Prettier)..."
exec bazel test //props/frontend:eslint_test //props/frontend:prettier_test
