#!/bin/bash
# Docker wrapper for Claude CLI using long-running containers
# Executes claude command inside the pre-configured container

# Check if container ID is provided
if [ -z "$CLAUDE_CONTAINER_ID" ]; then
    echo "ERROR: CLAUDE_CONTAINER_ID environment variable not set" >&2
    exit 1
fi

# Optional: Debug logging (remove in production)
echo "DEBUG: Container ID: $CLAUDE_CONTAINER_ID, Docker args: $@" >> /tmp/claude_debug.log

# Execute claude inside the existing Docker container
exec docker exec -i "$CLAUDE_CONTAINER_ID" claude --dangerously-skip-permissions "$@"