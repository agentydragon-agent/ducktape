#!/usr/bin/env bash
# Script to export UV workspace dependencies to requirements_bazel.txt for Bazel
set -euo pipefail

cd "$(dirname "$0")"

echo "Exporting UV workspace dependencies to requirements_bazel.txt..."
# Export all dependencies without hashes or editable installs
uv export --all-packages --no-hashes --no-editable > requirements_bazel_raw.txt

# Filter out local workspace members (lines starting with ./)
# Keep comments and actual package specs
grep -v '^\.\/' requirements_bazel_raw.txt > requirements_bazel.txt
rm requirements_bazel_raw.txt

echo "Successfully exported dependencies to requirements_bazel.txt"
echo "Dependencies exported: $(grep -c '^[a-z]' requirements_bazel.txt || echo 0)"
