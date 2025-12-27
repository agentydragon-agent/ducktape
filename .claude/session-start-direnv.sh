#!/bin/bash
set -e

# Only run in web environments
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    echo "Skipping development environment setup (local environment)"
    exit 0
fi

echo "Setting up development environment for Claude Code on the Web..." >&2
echo "NOTE: Nix/devenv installation is skipped due to container limitations." >&2
echo "      Only direnv will be set up. See comments in this script for details." >&2

# Nix installation fails in Claude Code containers due to process management issues
# Error: "cannot get exit status of PID: No child processes"
# This is a known limitation - Nix requires features not available in this environment
#
# Consequence: devenv-based .envrc files will not work
# Workaround: Use simple .envrc files that don't rely on devenv/Nix

# Install direnv if not already present
if ! command -v direnv &> /dev/null; then
    echo "Installing direnv..." >&2
    # Download and install direnv binary directly
    DIRENV_VERSION="2.35.0"
    DIRENV_ARCH="linux-amd64"
    curl -sfL "https://github.com/direnv/direnv/releases/download/v${DIRENV_VERSION}/direnv.${DIRENV_ARCH}" \
        -o /usr/local/bin/direnv
    chmod +x /usr/local/bin/direnv
    echo "direnv ${DIRENV_VERSION} installed successfully" >&2
else
    echo "direnv already installed: $(direnv version)" >&2
fi

# Allow all .envrc files in the project
if [ -n "$CLAUDE_PROJECT_DIR" ]; then
    cd "$CLAUDE_PROJECT_DIR"
    echo "Allowing .envrc files in project..." >&2
    if find . -name ".envrc" -type f 2>/dev/null | grep -q ".envrc"; then
        find . -name ".envrc" -type f | while read envrc; do
            echo "  Allowing $envrc" >&2
            direnv allow "$(dirname "$envrc")" 2>/dev/null || echo "    (failed to allow, will retry on first use)" >&2
        done
    else
        echo "  No .envrc files found" >&2
    fi
fi

# Export environment initialization to persist for subsequent bash commands
# Try outputting to STDOUT (maybe Claude Code captures this?)
echo "# direnv hook for .envrc activation"
echo "if command -v direnv &> /dev/null; then"
echo "    eval \"\$(direnv hook bash)\""
echo "fi"

echo "" >&2
echo "Development environment setup complete:" >&2
echo "  ✓ direnv: $(direnv version 2>/dev/null || echo 'installed')" >&2
echo "  ✗ Nix: skipped (container limitations)" >&2
echo "  ✗ devenv: skipped (requires Nix)" >&2
echo "" >&2
echo "NOTE: .envrc files using 'use devenv' will not work." >&2
echo "      Use simple .envrc files with standard shell commands instead." >&2
