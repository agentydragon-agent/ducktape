#!/bin/bash
# Bazel lint hook for pre-commit framework.
# Takes file paths as arguments, finds containing Bazel packages, runs ruff tests.

set -e

[ $# -eq 0 ] && exit 0

# Build regex pattern from files (escape dots, join with |)
PATTERN=$(printf '%s\n' "$@" | sed 's/\./\\./g' | tr '\n' '|' | sed 's/|$//')

# Find packages containing these files via Bazel query
PACKAGES=$(bazel query "attr('srcs', '.*($PATTERN).*', //...)" --output=package 2>/dev/null | \
    sort -u)

[ -z "$PACKAGES" ] && exit 0

# Build list of ruff test targets (filter to packages that have :ruff target)
RUFF_TARGETS=""
for pkg in $PACKAGES; do
    if bazel query "//$pkg:ruff" 2>/dev/null | grep -q ":ruff"; then
        RUFF_TARGETS="$RUFF_TARGETS //$pkg:ruff"
    fi
done

[ -z "$RUFF_TARGETS" ] && exit 0

echo "Running ruff tests:$RUFF_TARGETS"
exec bazel test $RUFF_TARGETS
