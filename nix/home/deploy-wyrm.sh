#!/usr/bin/env bash
# Deploy Wyrm with parallel Ansible + Nix/home-manager configuration
# This allows gradual migration from Ansible to Nix

set -e

DUCKTAPE_ROOT="$HOME/code/ducktape"

echo "=== Deploying Wyrm with Ansible + Nix (parallel mode) ==="
echo "Ducktape root: $DUCKTAPE_ROOT"

# Check prerequisites
if [ ! -d "$DUCKTAPE_ROOT" ]; then
    echo "Error: ducktape repository not found at $DUCKTAPE_ROOT"
    exit 1
fi

echo ">>> Step 1: Running Ansible (skipping migrated tasks)..."
cd "$DUCKTAPE_ROOT/ansible"
ansible-playbook wyrm.yaml --ask-become-pass --skip-tags "migrated_to_nix"

echo ">>> Step 2: Deploying home-manager configuration..."

# Check if home-manager is installed
if ! command -v home-manager &> /dev/null; then
    echo "home-manager not found. Installing..."
    nix-channel --add https://github.com/nix-community/home-manager/archive/release-24.05.tar.gz home-manager
    nix-channel --update
    nix-shell '<home-manager>' -A install
fi

cd "$DUCKTAPE_ROOT/nix/home"
home-manager switch -f home.nix

echo ">>> Step 3: Verifying configuration..."

echo "Checking Claude MCP configuration..."
if command -v claude &> /dev/null; then
    MCP_SERVERS=$(claude mcp list 2>/dev/null | wc -l)
    echo "✓ Claude Code installed with $MCP_SERVERS MCP servers"
else
    echo "⚠ Claude Code CLI not found in PATH"
fi

echo "Deployment complete. If issues arise, rollback with:"
echo "  home-manager rollback"
echo "  ansible-playbook wyrm.yaml --ask-become-pass  # without skip-tags"
