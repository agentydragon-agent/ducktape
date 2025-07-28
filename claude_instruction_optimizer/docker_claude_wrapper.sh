#!/bin/bash
# Simple transparent Docker wrapper for Claude CLI
# Just passes all arguments through to the containerized claude command

# Capture the current working directory for volume mounting
_cwd=$(pwd)

# Optional: Debug logging (remove in production)
echo "DEBUG: Docker args: $@" >> /tmp/claude_debug.log

# Execute claude inside Docker container, passing through all arguments unchanged
# Mount current directory as /workspace so files created in container are accessible on host
exec docker run --rm -i \
  -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  -v "${_cwd}:/workspace" \
  -w /workspace \
  claude-dev:latest \
  claude --dangerously-skip-permissions "$@"