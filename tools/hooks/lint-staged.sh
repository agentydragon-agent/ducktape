#!/bin/bash
# Bazel lint hook for pre-commit framework.
# Takes file paths as arguments, finds containing Bazel packages, runs lint.

set -e

[ $# -eq 0 ] && exit 0

# Build regex pattern from files (escape dots, join with |)
PATTERN=$(printf '%s\n' "$@" | sed 's/\./\\./g' | tr '\n' '|' | sed 's/|$//')

# Find packages containing these files via Bazel query
PACKAGES=$(bazel query "attr('srcs', '.*($PATTERN).*', //...)" --output=package 2>/dev/null | \
    sed 's|^|//|; s|$|:all|' | sort -u | tr '\n' ' ')

[ -z "$PACKAGES" ] && exit 0

echo "Linting: $PACKAGES"
exec bazel lint $PACKAGES
