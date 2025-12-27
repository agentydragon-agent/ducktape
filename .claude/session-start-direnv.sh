#!/bin/bash
set -e

# Only run in web environments
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    echo "Skipping direnv setup (local environment)"
    exit 0
fi

echo "Setting up direnv for Claude Code on the Web..."

# Install direnv if not already present
if ! command -v direnv &> /dev/null; then
    echo "Installing direnv..."
    curl -sfL https://direnv.net/install.sh | bash
fi

# Allow all .envrc files in the project
cd "$CLAUDE_PROJECT_DIR"
find . -name ".envrc" -type f | while read envrc; do
    echo "Allowing $envrc"
    direnv allow "$(dirname "$envrc")"
done

# Export direnv initialization to persist for subsequent bash commands
# This ensures direnv's environment is available in all subsequent bash calls
echo 'eval "$(direnv hook bash)"' >> "$CLAUDE_ENV_FILE"

echo "direnv setup complete"
