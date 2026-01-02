#!/bin/bash
# ESLint wrapper for sh_test
# Usage: run_eslint.sh <eslint_binary> <package_dir> [eslint_args...]

set -e

# Get absolute path before cd
ESLINT="$(realpath "$1")"
PKG_DIR="$2"
shift 2

cd "$PKG_DIR"
exec "$ESLINT" "$@"
