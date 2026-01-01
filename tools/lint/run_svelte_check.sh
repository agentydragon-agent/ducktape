#!/usr/bin/env bash
# Wrapper script to run svelte-check for Bazel sh_test
# Usage: run_svelte_check.sh <svelte_check_binary> <svelte_kit_binary> <package_dir> [svelte_check_args...]

set -euo pipefail

# Resolve binary paths before cd'ing
SVELTE_CHECK="$(realpath "$1")"
SVELTE_KIT="$(realpath "$2")"
PACKAGE_DIR="$3"
shift 3

# Change to the package directory in runfiles
cd "$PACKAGE_DIR"

# Run svelte-kit sync to generate .svelte-kit/tsconfig.json
"$SVELTE_KIT" sync

# Run svelte-check with remaining args
exec "$SVELTE_CHECK" "$@"
