#!/bin/bash
# Verify agent_core has no MCP dependencies
# The genquery output should be empty if there are no matches

# Find the genquery output file in runfiles
RUNFILES="${RUNFILES:-$0.runfiles}"
DEPS_FILE="$RUNFILES/_main/agent_core/agent_core_mcp_deps"

# Fallback for different runfiles layouts
if [[ ! -f "$DEPS_FILE" ]]; then
    DEPS_FILE="$RUNFILES/ducktape/agent_core/agent_core_mcp_deps"
fi

if [[ ! -f "$DEPS_FILE" ]]; then
    echo "ERROR: genquery output file not found"
    echo "Tried: $RUNFILES/_main/agent_core/agent_core_mcp_deps"
    echo "Tried: $RUNFILES/ducktape/agent_core/agent_core_mcp_deps"
    exit 1
fi

if [[ -s "$DEPS_FILE" ]]; then
    echo "ERROR: agent_core has unexpected MCP dependencies:"
    cat "$DEPS_FILE"
    exit 1
fi

echo "OK: agent_core has no MCP dependencies"
