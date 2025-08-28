#!/usr/bin/env bash
# Deploy Wyrm with parallel Ansible + Nix/home-manager configuration
# This allows gradual migration from Ansible to Nix

set -e

DUCKTAPE_ROOT="$HOME/code/ducktape"
ANSIBLE_DIR="$DUCKTAPE_ROOT/ansible"
NIX_HOME_DIR="$DUCKTAPE_ROOT/nix/home"

echo "=== Deploying Wyrm with Ansible + Nix (parallel mode) ==="
echo "Ducktape root: $DUCKTAPE_ROOT"

# Check prerequisites
if [ ! -d "$DUCKTAPE_ROOT" ]; then
    echo "Error: ducktape repository not found at $DUCKTAPE_ROOT"
    exit 1
fi

# 1. Run Ansible with migrated tasks skipped
echo ""
echo ">>> Step 1: Running Ansible (skipping migrated tasks)..."
cd "$ANSIBLE_DIR"

# Tags to skip (already migrated to Nix)
SKIP_TAGS="migrated_to_nix"

echo "Skipping tags: $SKIP_TAGS"
ansible-playbook wyrm.yaml --ask-become-pass --skip-tags "$SKIP_TAGS"

# 2. Deploy Nix home-manager configuration
echo ""
echo ">>> Step 2: Deploying home-manager configuration..."

# Check if home-manager is installed
if ! command -v home-manager &> /dev/null; then
    echo "home-manager not found. Installing..."
    nix-channel --add https://github.com/nix-community/home-manager/archive/release-24.05.tar.gz home-manager
    nix-channel --update
    nix-shell '<home-manager>' -A install
fi

cd "$NIX_HOME_DIR"
home-manager switch -f home.nix

# 3. Verify critical services
echo ""
echo ">>> Step 3: Verifying configuration..."

echo "Checking GNOME extensions..."
EXTENSIONS=$(dconf read /org/gnome/shell/enabled-extensions 2>/dev/null || echo "[]")
if [ "$EXTENSIONS" != "[]" ]; then
    echo "✓ GNOME extensions configured"
else
    echo "⚠ No GNOME extensions found"
fi

echo "Checking terminal profiles..."
PROFILES=$(dconf list /org/gnome/terminal/legacy/profiles:/ 2>/dev/null | wc -l)
if [ "$PROFILES" -gt 0 ]; then
    echo "✓ Found $PROFILES terminal profile(s)"
else
    echo "⚠ No terminal profiles found"
fi

echo "Checking Claude MCP configuration..."
if command -v claude &> /dev/null; then
    MCP_SERVERS=$(claude mcp list 2>/dev/null | wc -l)
    echo "✓ Claude Code installed with $MCP_SERVERS MCP servers"
else
    echo "⚠ Claude Code CLI not found in PATH"
fi

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Manual verification checklist:"
echo "  - [ ] Test theme switching with switch_gnome_terminal_profile"
echo "  - [ ] Verify Flameshot launches with Print key"
echo "  - [ ] Check autostart apps after logout/login"
echo "  - [ ] Test workspace switching (Ctrl+Alt+↑/↓)"
echo ""
echo "If issues arise, rollback with:"
echo "  home-manager rollback"
echo "  ansible-playbook wyrm.yaml --ask-become-pass  # without skip-tags"