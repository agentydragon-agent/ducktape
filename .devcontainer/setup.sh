#!/bin/bash
set -e

echo "=== Ducktape Development Container Setup ==="
echo ""

# Install Bazelisk if not already available
if ! command -v bazelisk &> /dev/null; then
    echo "Installing Bazelisk..."
    BAZELISK_VERSION="v1.24.0"
    BAZELISK_ARCH="linux-amd64"
    curl -fsSL "https://github.com/bazelbuild/bazelisk/releases/download/${BAZELISK_VERSION}/bazelisk-${BAZELISK_ARCH}" -o /usr/local/bin/bazelisk
    chmod +x /usr/local/bin/bazelisk
    ln -sf /usr/local/bin/bazelisk /usr/local/bin/bazel
    echo "✓ Bazelisk installed"
else
    echo "✓ Bazelisk already available"
fi

# Install claude_hooks package from tools/claude_hooks
echo ""
echo "Installing claude_hooks package..."
cd "${CLAUDE_PROJECT_DIR}/tools/claude_hooks"

# Use uv if available, otherwise pip
if command -v uv &> /dev/null; then
    echo "Using uv for installation..."
    uv pip install --system -e .
else
    echo "Using pip for installation..."
    pip3 install --user -e .
fi

echo "✓ claude_hooks package installed"

# Run session start hook in standard mode
echo ""
echo "Running session start hook..."
cd "${CLAUDE_PROJECT_DIR}"

# Create a minimal hook input JSON for the session start hook
HOOK_INPUT=$(cat <<HOOK_JSON
{
  "session_id": "devcontainer-setup",
  "cwd": "${CLAUDE_PROJECT_DIR}",
  "transcript_path": "/tmp/devcontainer-transcript",
  "hook_event_name": "SessionStart",
  "source": "startup"
}
HOOK_JSON
)

echo "$HOOK_INPUT" | python3 -m tools.claude_hooks.session_start || {
    echo "Warning: Session start hook failed, but continuing..."
}

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Environment file created at: ${CLAUDE_ENV_FILE}"
echo "Source it in your shell: source ${CLAUDE_ENV_FILE}"
echo ""
echo "To use the environment in your shell, add this to your ~/.bashrc or ~/.zshrc:"
echo "  [ -f ${CLAUDE_ENV_FILE} ] && source ${CLAUDE_ENV_FILE}"
echo ""
