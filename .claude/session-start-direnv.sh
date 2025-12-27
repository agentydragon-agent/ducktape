#!/bin/bash
set -e

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
if [ -n "$CLAUDE_ENV_FILE" ]; then
    echo "Writing direnv hook to: $CLAUDE_ENV_FILE"
    cat >> "$CLAUDE_ENV_FILE" << 'EOF'
# direnv hook for .envrc activation
if command -v direnv &> /dev/null; then
    eval "$(direnv hook bash)"
fi
EOF
    echo "Environment persistence configured successfully"
else
    echo "WARNING: CLAUDE_ENV_FILE not set - falling back to ~/.bashrc"
    # Fallback: write to bashrc if CLAUDE_ENV_FILE is not available
    if ! grep -q "claude-direnv-setup" ~/.bashrc 2>/dev/null; then
        cat >> ~/.bashrc << 'EOF'
# claude-direnv-setup
if command -v direnv &> /dev/null; then
    eval "$(direnv hook bash)"
fi
EOF
        echo "Environment persistence configured via ~/.bashrc"
    fi
fi

echo ""
echo "Development environment setup complete:"
echo "  ✓ direnv: $(direnv version 2>/dev/null || echo 'installed')"
echo "  ✗ Nix: skipped (container limitations)"
echo "  ✗ devenv: skipped (requires Nix)"
echo ""
echo "NOTE: .envrc files using 'use devenv' will not work."
echo "      Use simple .envrc files with standard shell commands instead."
