#!/usr/bin/env bash
# Wrapper script to run prettier for Bazel sh_test
# Usage: run_prettier.sh <prettier_binary> <package_dir> [prettier_args...]

set -euo pipefail

# Resolve the binary path before cd'ing
PRETTIER="$(realpath "$1")"
PACKAGE_DIR="$2"
shift 2

# Change to the package directory in runfiles
cd "$PACKAGE_DIR"

# Run prettier with remaining args
exec "$PRETTIER" "$@"
