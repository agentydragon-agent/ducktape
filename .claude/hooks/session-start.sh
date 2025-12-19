#!/bin/bash
# SessionStart hook for Claude Code Web - ducktape repository
#
# This hook sets up the environment for running tests in the Anthropic-hosted
# Claude Code Web environment (microVM).
#
# Reference: https://code.claude.com/docs/en/hooks
# Known limitations: https://github.com/anthropics/claude-code/issues/10367
#
# This script handles:
# 1. Podman installation and configuration (Docker API compatibility)
# 2. direnv installation
# 3. Project-specific setup based on working directory

set -euo pipefail

# Only run in Claude Code Web environment
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    echo "Not in Claude Code Web environment, skipping setup"
    exit 0
fi

echo "=== Claude Code Web Session Start Hook ==="
echo "Working directory: $(pwd)"

# Track what we've done for the summary
SETUP_STEPS=()

#############################################################################
# 1. Install and configure Podman for Docker API compatibility
#
# The Claude Code Web microVM has an incomplete /proc filesystem which
# prevents nested container network namespaces from working. We use:
# - vfs storage driver (required, overlay doesn't work on 9p)
# - runc runtime (more compatible than crun in this environment)
# - host networking only (network=none/bridge don't work)
#############################################################################

setup_podman() {
    if command -v podman &>/dev/null && [ -S /var/run/docker.sock ]; then
        # Verify the socket works
        if curl -s --unix-socket /var/run/docker.sock http://localhost/_ping | grep -q "OK"; then
            echo "✓ Podman already configured and working"
            return 0
        fi
    fi

    echo "Installing Podman and runc..."
    apt-get update -qq
    apt-get install -y -qq podman runc >/dev/null 2>&1

    # Configure vfs storage (required for microVM 9p filesystem)
    cat > /etc/containers/storage.conf << 'EOF'
[storage]
driver = "vfs"
runroot = "/tmp/containers-run"
graphroot = "/tmp/containers-storage"
EOF

    # Reset podman storage
    podman system reset -f 2>/dev/null || true

    # Start podman API service in background
    podman --storage-driver=vfs --runtime=/usr/sbin/runc system service -t 0 unix:///run/podman/podman.sock &
    sleep 2

    # Create Docker-compatible socket symlink
    ln -sf /run/podman/podman.sock /var/run/docker.sock

    # Verify it works
    if curl -s --unix-socket /var/run/docker.sock http://localhost/_ping | grep -q "OK"; then
        echo "✓ Podman configured with Docker API compatibility"
        SETUP_STEPS+=("Podman: Docker API at /var/run/docker.sock")
    else
        echo "⚠ Podman API may not be fully functional"
        SETUP_STEPS+=("Podman: Installed but API check failed")
    fi
}

#############################################################################
# 2. Install direnv
#############################################################################

setup_direnv() {
    if command -v direnv &>/dev/null; then
        echo "✓ direnv already installed"
        return 0
    fi

    echo "Installing direnv..."
    apt-get install -y -qq direnv >/dev/null 2>&1

    echo "✓ direnv installed"
    SETUP_STEPS+=("direnv: Installed")
}

#############################################################################
# 3. Project-specific setup (adgn)
#############################################################################

setup_adgn() {
    local adgn_dir

    # Find adgn directory
    if [ -d "./adgn" ]; then
        adgn_dir="./adgn"
    elif [ -f "./pyproject.toml" ] && grep -q 'name = "adgn"' ./pyproject.toml 2>/dev/null; then
        adgn_dir="."
    else
        echo "ℹ Not in adgn project, skipping Python setup"
        return 0
    fi

    echo "Setting up adgn Python environment..."

    # Use uv to sync dependencies
    if command -v uv &>/dev/null; then
        (cd "$adgn_dir" && uv sync --extra dev 2>&1 | tail -5)
        echo "✓ Python dependencies synced"
        SETUP_STEPS+=("Python: Dependencies installed via uv sync --extra dev")
    else
        echo "⚠ uv not found, skipping Python setup"
        SETUP_STEPS+=("Python: uv not found")
    fi

    # Install pre-commit if available
    if [ -f "$adgn_dir/.venv/bin/pre-commit" ]; then
        (cd "$adgn_dir" && .venv/bin/pre-commit install --install-hooks 2>&1 | tail -3) || true
        echo "✓ pre-commit hooks installed"
        SETUP_STEPS+=("pre-commit: Hooks installed")
    fi
}

#############################################################################
# 4. Set environment variables for testing
#############################################################################

setup_test_env() {
    # Write persistent environment variables
    if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
        cat >> "$CLAUDE_ENV_FILE" << 'EOF'
# Claude Code Web test configuration
# Reference: adgn/src/adgn/testing/claude_code_web.py
export ADGN_TEST_NETWORK_MODE=host
export DOCKER_HOST=unix:///var/run/docker.sock
EOF
        echo "✓ Test environment variables configured"
        SETUP_STEPS+=("Environment: ADGN_TEST_NETWORK_MODE=host")
    fi
}

#############################################################################
# Main execution
#############################################################################

# Run setup steps
setup_podman
setup_direnv
setup_adgn
setup_test_env

#############################################################################
# Summary
#############################################################################

echo ""
echo "=== Setup Complete ==="
echo "Summary:"
for step in "${SETUP_STEPS[@]}"; do
    echo "  - $step"
done
echo ""
echo "Notes:"
echo "  - Network isolation NOT supported (use host networking)"
echo "  - Tests marked @requires_network_isolation will be skipped"
echo "  - Run tests with: uv run pytest <path> -v"
