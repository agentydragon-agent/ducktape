#!/bin/bash
# Bazel lint hook for frontend files (ESLint via aspect).
# Runs ESLint on any changed JS/TS/Svelte files via the unified aspect.

set -e

[ $# -eq 0 ] && exit 0

# Check if any JS/TS/Svelte files changed
JS_FILES=$(printf '%s\n' "$@" | grep -E '\.(ts|js|svelte|tsx)$' || true)
[ -z "$JS_FILES" ] && exit 0

echo "Running ESLint via Bazel aspect on changed files..."
# Run eslint config on all targets (aspect will only lint changed files' targets)
exec bazel build --config=eslint --keep_going //...
