#!/usr/bin/env bash
# Check that no package pyproject.toml files contain ruff configuration
# All ruff config should be centralized in /ruff.toml

set -euo pipefail

# Find package pyproject.toml files with [tool.ruff] sections
# Exclude: root pyproject.toml and llm/repo-template (intentional exceptions)
files=$(find . -name "pyproject.toml" -type f \
  ! -path "./pyproject.toml" \
  ! -path "*/repo-template/*" \
  -exec grep -l "^\[tool\.ruff" {} \; 2>/dev/null || true)

if [ -n "$files" ]; then
  echo "❌ Found ruff config in package pyproject.toml files (should be in ruff.toml):"
  echo "$files"
  echo ""
  echo "Ruff configuration must be centralized in /ruff.toml"
  echo "Package pyproject.toml files may only list ruff as a dev dependency"
  exit 1
fi

echo "✓ No ruff configuration in package pyproject.toml files"
