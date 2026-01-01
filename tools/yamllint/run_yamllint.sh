#!/usr/bin/env bash
# Wrapper script to run yamllint for Bazel sh_test
# Usage: run_yamllint.sh <yamllint_binary> <package_dir> <config_file> [files_or_dirs...]

set -euo pipefail

# Resolve the binary path before cd'ing
YAMLLINT="$(realpath "$1")"
PACKAGE_DIR="$2"
CONFIG="$3"
shift 3

# Change to the package directory
cd "$PACKAGE_DIR"

# Run yamllint with the config file
exec "$YAMLLINT" -c "$CONFIG" "$@"
