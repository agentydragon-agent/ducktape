#!/bin/bash
# Verify that //mcp_infra/exec:subprocess_exec has no fastmcp in transitive deps.
# This is critical for in-container agent loops that need minimal dependencies.

set -euo pipefail

# Query transitive deps of subprocess_exec
deps=$(bazel query 'deps(//mcp_infra/exec:subprocess_exec)' 2>/dev/null || echo "")

# Check for fastmcp
if echo "$deps" | grep -q "fastmcp"; then
    echo "ERROR: subprocess_exec has fastmcp in transitive dependencies!"
    echo "This breaks in-container agent loops that need minimal deps."
    echo ""
    echo "Offending deps:"
    echo "$deps" | grep "fastmcp"
    exit 1
fi

echo "OK: subprocess_exec has no fastmcp dependency"
