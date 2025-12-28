#!/bin/bash
set -e

# Set up logging to predictable location
LOG_FILE="${CLAUDE_PROJECT_DIR:-$HOME}/.claude/session-start.log"
mkdir -p "$(dirname "$LOG_FILE")"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== Session Start Hook - $(date -Iseconds) ==="

# Only run in web environments
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    echo "Skipping development environment setup (local environment)"
    exit 0
fi

echo "Setting up development environment for Claude Code on the Web..."
echo "NOTE: Nix/devenv installation is skipped due to container limitations."
echo "      Only direnv will be set up. See comments in this script for details."

# Nix installation fails in Claude Code containers due to process management issues
# Error: "cannot get exit status of PID: No child processes"
# This is a known limitation - Nix requires features not available in this environment
#
# Consequence: devenv-based .envrc files will not work
# Workaround: Use simple .envrc files that don't rely on devenv/Nix

# Install direnv if not already present
if ! command -v direnv &> /dev/null; then
    echo "Installing direnv..."
    # Download and install direnv binary directly
    DIRENV_VERSION="2.35.0"
    DIRENV_ARCH="linux-amd64"
    curl -sfL "https://github.com/direnv/direnv/releases/download/v${DIRENV_VERSION}/direnv.${DIRENV_ARCH}" \
        -o /usr/local/bin/direnv
    chmod +x /usr/local/bin/direnv
    echo "direnv ${DIRENV_VERSION} installed successfully"
else
    echo "direnv already installed: $(direnv version)"
fi

# Install and configure pre-commit hooks
echo "Setting up pre-commit hooks..."
if ! command -v pre-commit &> /dev/null; then
    echo "  Installing pre-commit..."
    pip install --quiet pre-commit==4.0.1
    echo "  pre-commit installed successfully"
else
    echo "  pre-commit already installed: $(pre-commit --version)"
fi

# Install the git hooks
if [ -d ".git" ]; then
    echo "  Installing git hooks..."
    pre-commit install 2>&1 | sed 's/^/    /'
else
    echo "  Skipping git hook installation (not a git repository)"
fi

# Allow all .envrc files in the project
if [ -n "$CLAUDE_PROJECT_DIR" ]; then
    cd "$CLAUDE_PROJECT_DIR"
    echo "Allowing .envrc files in project..."
    if find . -name ".envrc" -type f 2>/dev/null | grep -q ".envrc"; then
        find . -name ".envrc" -type f | while read envrc; do
            echo "  Allowing $envrc"
            direnv allow "$(dirname "$envrc")" 2>/dev/null || echo "    (failed to allow, will retry on first use)"
        done
    else
        echo "  No .envrc files found"
    fi
fi

# Export environment initialization to persist for subsequent bash commands
# Try outputting to STDOUT (maybe Claude Code captures this?)
echo "# direnv hook for .envrc activation"
echo "if command -v direnv &> /dev/null; then"
echo "    eval \"\$(direnv hook bash)\""
echo "fi"

echo ""
echo "Development environment setup complete:"
echo "  ✓ direnv: $(direnv version 2>/dev/null || echo 'installed')"
echo "  ✓ pre-commit: $(pre-commit --version 2>/dev/null || echo 'installed')"
echo "  ✗ Nix: skipped (container limitations)"
echo "  ✗ devenv: skipped (requires Nix)"
echo ""
echo "NOTE: .envrc files using 'use devenv' will not work."
echo "      Use simple .envrc files with standard shell commands instead."
echo ""
echo "Log file: $LOG_FILE"
